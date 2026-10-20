"""Alias for services.youtube.youtube_handler; one module object keeps `init_youtube()` state shared."""

import importlib
import sys

# Import the canonical module directly (services.youtube.youtube_handler)
# without triggering the heavy services/__init__.py top-level imports.
_youtube_handler = importlib.import_module("services.youtube.youtube_handler")

sys.modules[__name__] = _youtube_handler
