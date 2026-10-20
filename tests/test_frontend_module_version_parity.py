import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_local_modules_have_one_identity_across_imports_html_and_cache():
    static = ROOT / "static"
    sources = [*static.rglob("*.js"), static / "index.html"]
    identities: dict[Path, dict[str, list[str]]] = {}

    for path in sources:
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(
            r"['\"]((?:/static/|\.\.?/)[^'\"]+\.js)(?:\?v=([A-Za-z0-9_-]+))?['\"]",
            source,
        ):
            specifier, version = match.groups()
            if specifier.startswith("/static/"):
                target = static / specifier.removeprefix("/static/")
            else:
                target = path.parent / specifier
            target = target.resolve()
            identity = version or "unversioned"
            line = source.count("\n", 0, match.start()) + 1
            identities.setdefault(target, {}).setdefault(identity, []).append(
                f"{path.relative_to(ROOT)}:{line}"
            )

    conflicts = {
        str(path.relative_to(ROOT)): versions
        for path, versions in identities.items()
        if len(versions) > 1
    }
    assert not conflicts, f"local modules loaded under multiple URL identities: {conflicts}"
