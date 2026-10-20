from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_chat_and_app_share_one_session_module_instance():
    app = (ROOT / "static/app.js").read_text(encoding="utf-8")
    index = (ROOT / "static/index.html").read_text(encoding="utf-8")
    service_worker = (ROOT / "static/sw.js").read_text(encoding="utf-8")

    assert "from './js/sessions.js';" in app
    assert "sessions.js?v=" not in app
    assert 'href="/static/js/sessions.js"' in index
    assert 'src="/static/js/sessions.js"' in index
    assert "'/static/js/sessions.js'" in service_worker
