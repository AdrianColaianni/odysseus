from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_local_dependency_probe_refreshes_user_site_visibility():
    source = (ROOT / "routes/shell_routes.py").read_text(encoding="utf-8")

    assert "importlib.invalidate_caches()" in source
    assert "user_site = site.getusersitepackages()" in source
    # addsitedir (not a bare sys.path.append) so user-site `.pth` hooks are
    # replayed when a package is installed into an already-running process —
    # otherwise setuptools' distutils shim never activates and basicsr-based
    # deps (realesrgan) probe as not-installed until a restart. See #4810.
    assert "if user_site and os.path.isdir(user_site):" in source
    assert "site.addsitedir(user_site)" in source
