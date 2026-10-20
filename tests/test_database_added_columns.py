"""init_db adds the columns an older database lacks, without touching its rows."""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import core.database as database


def test_init_db_adds_a_missing_column_with_its_default_and_keeps_rows(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    database.Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE sessions DROP COLUMN memory_extraction_enabled"))
        conn.execute(text(
            "INSERT INTO sessions (id, name, endpoint_url, model, created_at, updated_at) "
            "VALUES ('legacy', 'Old chat', 'http://llm.invalid', 'm', '2020-01-01', '2020-01-01')"
        ))
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine))

    database.init_db()
    database.init_db()

    assert "memory_extraction_enabled" in {c["name"] for c in inspect(engine).get_columns("sessions")}
    with engine.connect() as conn:
        row = conn.execute(text("SELECT name, memory_extraction_enabled FROM sessions")).one()
    assert tuple(row) == ("Old chat", 1)
    engine.dispose()
