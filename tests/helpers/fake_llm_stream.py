"""A stand-in for `httpx.AsyncClient` that serves canned SSE completions.

Use with `monkeypatch.setattr(module.httpx, "AsyncClient", sse_client(...))`
for code that calls `client.stream(...)` and reads `aiter_lines()`. Not for
code that calls `client.post` or reads `aiter_bytes`.
"""
import json


def sse_client(responses, requests=None):
    """Return a client class whose `stream()` calls serve `responses` in order.

    Each item is one provider response: a dict is sent as one `data:` line, a
    list of dicts as one line each, and `[DONE]` follows either. The JSON body
    of every request is appended to `requests` when given. Running past the
    last response raises StopIteration, so an unexpected extra round fails.
    """
    pending = iter(responses)

    class _Response:
        def __init__(self, packets):
            self.packets = packets if isinstance(packets, list) else [packets]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            for packet in self.packets:
                yield "data: " + json.dumps(packet)
            yield "data: [DONE]"

    class _Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, *args, **kwargs):
            if requests is not None:
                requests.append(kwargs.get("json"))
            return _Response(next(pending))

    return _Client
