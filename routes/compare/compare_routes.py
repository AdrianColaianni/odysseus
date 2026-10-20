"""Model A/B comparison routes."""
import json
import uuid
import random
from datetime import datetime
from fastapi import APIRouter, Form, HTTPException, Request, Depends
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
import logging

from core.database import Comparison, SessionLocal, get_db
from core.session_manager import SessionManager
from src.auth_helpers import get_current_user
from routes.session_routes import _reject_raw_endpoint_url_for_non_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/compare", tags=["compare"])


def _owned_endpoint_by_url(db, base_url, owner):
    """The endpoint with this base_url visible to `owner` (own or shared rows).

    Owner-scoped because start_comparison copies its api_key into the caller's
    [CMP] session.
    """
    from core.database import ModelEndpoint
    from src.auth_helpers import owner_filter
    q = db.query(ModelEndpoint).filter(ModelEndpoint.base_url == base_url)
    return owner_filter(q, ModelEndpoint, owner).first()


def _owned_endpoint_by_id(db, endpoint_id, owner):
    """The endpoint with this id visible to `owner` (own or shared rows).

    Preferred over the base_url match: two endpoints can share a base_url with
    different api_keys.
    """
    from core.database import ModelEndpoint
    from src.auth_helpers import owner_filter
    q = db.query(ModelEndpoint).filter(ModelEndpoint.id == endpoint_id)
    return owner_filter(q, ModelEndpoint, owner).first()


class RecordVoteRequest(BaseModel):
    prompt: str
    models: List[str]
    winner: str           # model name or "tie"
    is_blind: bool = True


def setup_compare_routes(session_manager: SessionManager):
    """Setup comparison routes."""

    @router.post("/start")
    def start_comparison(
        request: Request,
        prompt: str = Form(...),
        model_a: str = Form(...),
        model_b: str = Form(...),
        endpoint_a: str = Form(""),
        endpoint_b: str = Form(""),
        endpoint_a_id: str = Form(""),
        endpoint_b_id: str = Form(""),
        is_blind: str = Form("true"),
    ):
        """Create two ephemeral sessions and a comparison record.

        Returns the comparison ID and the two session IDs so the client
        can fire two independent SSE streams to /api/chat_stream.
        """
        user = getattr(request.state, 'current_user', None)
        comp_id = str(uuid.uuid4())
        sid_a = str(uuid.uuid4())
        sid_b = str(uuid.uuid4())

        # Blind mapping: randomly assign left/right
        blind = str(is_blind).lower() == "true"
        if blind:
            mapping = {"left": "a", "right": "b"}
            if random.random() > 0.5:
                mapping = {"left": "b", "right": "a"}
        else:
            mapping = {"left": "a", "right": "b"}

        # Map session IDs to left/right based on blind mapping
        session_left = sid_a if mapping["left"] == "a" else sid_b
        session_right = sid_a if mapping["right"] == "a" else sid_b

        # Blind sessions are named by slot so the sidebar does not leak the model.
        slot_name = {session_left: "Model A", session_right: "Model B"}

        # Validate both endpoints before creating any session, so a rejection
        # leaves no half-built [CMP] session holding a copied auth header.
        from src.endpoint_resolver import build_chat_url, build_headers, normalize_base
        resolved = []
        db = SessionLocal()
        try:
            for sid, model, endpoint, endpoint_id in [
                (sid_a, model_a, endpoint_a, endpoint_a_id),
                (sid_b, model_b, endpoint_b, endpoint_b_id),
            ]:
                eid = endpoint_id.strip() if isinstance(endpoint_id, str) else ""
                if eid:
                    ep = _owned_endpoint_by_id(db, eid, user)
                    if ep is None:
                        # No fallback to a same-URL row: it may hold a different key.
                        raise HTTPException(404, "Model endpoint not found")
                    endpoint = ep.base_url
                elif not endpoint:
                    raise HTTPException(
                        422, "endpoint_a/endpoint_b or endpoint_a_id/endpoint_b_id is required"
                    )
                else:
                    base = normalize_base(endpoint)
                    ep = _owned_endpoint_by_url(db, base, user)
                # Only unregistered raw URLs are rejected for non-admins.
                _reject_raw_endpoint_url_for_non_admin(
                    request, user, str(ep.id) if ep is not None else None, endpoint
                )
                # Dial the registered row's vetted URL; a raw URL survives only
                # for callers allowed to pass one (admins, single-user mode).
                session_endpoint_url = (
                    build_chat_url(normalize_base(ep.base_url)) if ep is not None else endpoint
                )
                headers = build_headers(ep.api_key, ep.base_url) if (ep and ep.api_key) else None
                resolved.append((sid, model, session_endpoint_url, headers))
        finally:
            db.close()

        for sid, model, session_endpoint_url, headers in resolved:
            name = f"[CMP] {slot_name[sid]}" if blind else f"[CMP] {model.split('/')[-1]}"
            session_manager.create_session(
                session_id=sid,
                name=name,
                endpoint_url=session_endpoint_url,
                model=model,
                rag=False,
                owner=user,
            )
            if headers:
                s = session_manager.sessions.get(sid)
                if s:
                    s.headers = headers

        db = SessionLocal()
        try:
            comp = Comparison(
                id=comp_id,
                prompt=prompt,
                model_a=model_a,
                model_b=model_b,
                # Id-only callers record the resolved URL; resolved is in [a, b] order.
                endpoint_a=endpoint_a or resolved[0][2],
                endpoint_b=endpoint_b or resolved[1][2],
                is_blind=blind,
                blind_mapping=json.dumps(mapping),
                owner=user,
            )
            db.add(comp)
            db.commit()
        finally:
            db.close()

        # Blind mode withholds models and mapping until the vote reveals them.
        return {
            "id": comp_id,
            "session_left": session_left,
            "session_right": session_right,
            "model_left": None if blind else (model_a if mapping["left"] == "a" else model_b),
            "model_right": None if blind else (model_a if mapping["right"] == "a" else model_b),
            "is_blind": blind,
            "mapping": None if blind else mapping,
        }

    @router.post("/{comp_id}/vote")
    def vote_comparison(
        request: Request,
        comp_id: str,
        winner: str = Form(...),  # "left", "right", or "tie"
        db: Session = Depends(get_db),
    ):
        """Record the user's vote and reveal model names if blind."""
        user = get_current_user(request)
        comp = db.query(Comparison).filter(Comparison.id == comp_id).first()
        if not comp:
            raise HTTPException(404, "Comparison not found")
        if user and comp.owner != user:
            raise HTTPException(404, "Comparison not found")
        if comp.winner:
            raise HTTPException(400, "Already voted")

        mapping = json.loads(comp.blind_mapping) if comp.blind_mapping else {"left": "a", "right": "b"}

        if winner == "tie":
            comp.winner = "tie"
        elif winner == "left":
            comp.winner = mapping["left"]
        elif winner == "right":
            comp.winner = mapping["right"]
        else:
            raise HTTPException(400, "winner must be 'left', 'right', or 'tie'")

        comp.voted_at = datetime.utcnow()
        db.commit()

        return {
            "winner": comp.winner,
            "model_a": comp.model_a,
            "model_b": comp.model_b,
            "revealed": {
                "left": comp.model_a if mapping["left"] == "a" else comp.model_b,
                "right": comp.model_a if mapping["right"] == "a" else comp.model_b,
            },
        }

    @router.post("/record")
    def record_comparison(request: Request, body: RecordVoteRequest, db: Session = Depends(get_db)):
        """Lightweight endpoint to record a comparison vote from the frontend."""
        user = get_current_user(request)
        comp_id = str(uuid.uuid4())

        model_a = body.models[0] if len(body.models) > 0 else ""
        model_b = body.models[1] if len(body.models) > 1 else ""

        # For N>2 models, store the full list as JSON in blind_mapping
        if len(body.models) > 2:
            blind_mapping = json.dumps({"models": body.models})
        else:
            blind_mapping = None

        comp = Comparison(
            id=comp_id,
            prompt=body.prompt[:500],
            model_a=model_a,
            model_b=model_b,
            endpoint_a="",
            endpoint_b="",
            winner=body.winner,
            is_blind=body.is_blind,
            blind_mapping=blind_mapping,
            voted_at=datetime.utcnow(),
            owner=user,
        )
        db.add(comp)
        db.commit()

        return {"status": "ok", "id": comp_id}

    @router.delete("/{comp_id}")
    def delete_comparison(request: Request, comp_id: str, db: Session = Depends(get_db)):
        """Delete a comparison and its ephemeral sessions."""
        user = get_current_user(request)
        comp = db.query(Comparison).filter(Comparison.id == comp_id).first()
        if not comp:
            raise HTTPException(404, "Comparison not found")
        if user and comp.owner != user:
            raise HTTPException(404, "Comparison not found")
        db.delete(comp)
        db.commit()
        return {"status": "deleted"}

    return router
