from pathlib import Path


def test_env_file_is_optional_and_ignored():
    """A fresh checkout should not require a private .env file."""
    gitignore = Path(__file__).resolve().parents[1] / ".gitignore"
    ignored = {line.strip() for line in gitignore.read_text(encoding="utf-8").splitlines()}
    assert ".env" in ignored, ".env should stay local and ignored"
