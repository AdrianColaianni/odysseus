"""Cookbook HF token persistence and lookup."""

import json

from routes import cookbook_helpers
from routes.cookbook_helpers import load_stored_hf_token
from src.secret_storage import encrypt


def test_load_stored_hf_token_reads_encrypted_state(tmp_path, monkeypatch):
    state_path = tmp_path / "cookbook_state.json"
    monkeypatch.setattr(cookbook_helpers, "COOKBOOK_STATE_FILE", str(state_path))
    state_path.write_text(
        json.dumps({"env": {"hfToken": encrypt("hf_test_token_12345")}}),
        encoding="utf-8",
    )
    assert load_stored_hf_token() == "hf_test_token_12345"


def test_load_stored_hf_token_falls_back_to_env_when_state_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(cookbook_helpers, "COOKBOOK_STATE_FILE", str(tmp_path / "cookbook_state.json"))
    monkeypatch.setenv("HF_TOKEN", "hf_from_env")
    assert load_stored_hf_token() == "hf_from_env"


def test_load_stored_hf_token_prefers_state_over_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_from_env")
    state_path = tmp_path / "cookbook_state.json"
    monkeypatch.setattr(cookbook_helpers, "COOKBOOK_STATE_FILE", str(state_path))
    state_path.write_text(
        json.dumps({"env": {"hfToken": encrypt("hf_from_state")}}),
        encoding="utf-8",
    )
    assert load_stored_hf_token() == "hf_from_state"
