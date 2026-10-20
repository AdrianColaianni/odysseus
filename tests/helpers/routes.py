"""Find a route's endpoint function on a FastAPI router or app.

Use when a test calls an endpoint directly instead of through `TestClient`.
Not for routes that need middleware or dependency resolution: drive those
through the app.
"""


def route_endpoint(router, path: str, method: str):
    """The endpoint registered for `method` on `path`; fails the test if absent."""
    method = method.upper()
    for route in router.routes:
        if route.path == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")
