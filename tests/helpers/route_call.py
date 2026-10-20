"""Call a route endpoint directly, supplying the session Depends(get_db) would."""

import inspect
import sys
from contextlib import contextmanager


@contextmanager
def _db_session(endpoint):
    # A test that patched the route module's SessionLocal expects that factory;
    # otherwise use whatever `core.database` is loaded, stub or real.
    factory = getattr(sys.modules.get(endpoint.__module__), "SessionLocal", None)
    if factory is None:
        sessions = sys.modules["core.database"].get_db()
        try:
            yield next(sessions)
        finally:
            sessions.close()
        return
    db = factory()
    try:
        yield db
    finally:
        db.close()


def with_db(endpoint):
    """Wrap `endpoint` so a direct call gets the `db` that `Depends(get_db)` would give.

    Endpoints without a `db` parameter come back unchanged.
    """
    if "db" not in inspect.signature(endpoint).parameters:
        return endpoint
    if inspect.iscoroutinefunction(endpoint):
        async def call_async(*args, **kwargs):
            if "db" in kwargs:
                return await endpoint(*args, **kwargs)
            with _db_session(endpoint) as db:
                return await endpoint(*args, db=db, **kwargs)
        return call_async

    def call(*args, **kwargs):
        if "db" in kwargs:
            return endpoint(*args, **kwargs)
        with _db_session(endpoint) as db:
            return endpoint(*args, db=db, **kwargs)
    return call
