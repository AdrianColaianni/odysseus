"""The one filesystem confinement check: is this path inside that root.

Rules every caller relies on:
- Both sides are canonicalized (realpath); canonicalizing one side breaks on
  symlinked roots such as macOS /tmp.
- ``commonpath``, never ``startswith``: ``/a/bc`` is not inside ``/a/b``.
- A relative candidate joins the root, never the process cwd.
- NUL and newline raise ValueError; ``commonpath`` raising means outside.

Sensitive-path deny lists (``.ssh``, ...) live with their callers, such as
src/tool_execution. Process confinement is src.containment.
"""

from __future__ import annotations

import os

__all__ = [
    "PathEscape",
    "canonical_root",
    "confine",
    "is_inside",
]


class PathEscape(ValueError):
    """A candidate path does not resolve inside the root it was checked against.

    A subclass of :class:`ValueError` so the call sites this replaces — which
    raise ``ValueError`` and are caught as such by their callers and their
    tests — keep behaving the way they did.
    """

    def __init__(self, root: str, candidate: str, reason: str = "") -> None:
        self.root = str(root)
        self.candidate = str(candidate)
        self.reason = str(reason or "outside the allowed root")
        super().__init__(
            f"path {self.candidate!r} is {self.reason} ({self.root})"
        )


def _reject_unusable(value: str, *, label: str) -> str:
    """Normalize a path argument to ``str``, refusing the unusable shapes.

    ``\\x00`` is refused here because the OS layer raises on it much later and
    from somewhere unhelpful, and because a broad ``except Exception`` around
    the comparison would otherwise record it as an ordinary escape. Newlines
    are refused for the same reason the workspace-mount parser refuses them:
    a path carrying one has been built by splitting something that was not a
    path list.
    """
    if value is None:
        raise ValueError(f"{label} is required")
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a path, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} is required")
    if "\x00" in text:
        raise ValueError(f"{label} must not contain NUL")
    if "\n" in text or "\r" in text:
        raise ValueError(f"{label} must not contain a newline")
    return text


def canonical_root(root) -> str:
    """The canonical form of a confinement root.

    Exposed because a caller that holds a root across several checks should
    canonicalize it once, and because a caller comparing two paths itself needs
    the same canonical form this module compares against — a realpath-ed value
    tested against a raw one is the asymmetry this module exists to remove.
    """
    text = _reject_unusable(root, label="root")
    return os.path.realpath(os.path.expanduser(text))


def _canonical_candidate(root: str, candidate) -> str:
    """Canonicalize ``candidate``, resolving a relative path under ``root``.

    ``realpath`` is deliberately the non-strict kind: a final component that
    does not exist yet is normalized rather than refused, because a write target
    is a legitimate thing to confine. Everything that *does* exist is resolved,
    so a symlink anywhere in the chain — including the final component — is
    followed before the comparison rather than after the open.
    """
    text = _reject_unusable(candidate, label="path")
    expanded = os.path.expanduser(text)
    if not os.path.isabs(expanded):
        expanded = os.path.join(root, expanded)
    return os.path.realpath(expanded)


def is_inside(root, candidate, *, allow_root: bool = True) -> bool:
    """True when ``candidate`` resolves inside ``root``.

    The boolean form, for call sites whose contract is a predicate. A malformed
    argument is ``False`` here rather than a raise, because a predicate that
    raises is the reason those call sites wrapped themselves in
    ``except Exception`` in the first place. Use :func:`confine` where the
    caller wants the resolved path and a reason for the refusal.

    ``allow_root=False`` excludes the root itself, for a caller whose operation
    is only meaningful on something *under* the root — deleting a file, say,
    where the root is the directory it must not be.
    """
    try:
        confine(root, candidate, allow_root=allow_root)
        return True
    except (ValueError, OSError):
        return False


def confine(root, candidate, *, allow_root: bool = True) -> str:
    """Resolve ``candidate`` inside ``root``, or raise.

    Returns the canonical absolute path, which is what the caller should then
    open: resolving and then opening the *original* string re-introduces the
    symlink race the resolution just closed.

    :raises ValueError: either argument is unusable as a path.
    :raises PathEscape: the candidate resolves outside the root.
    """
    base = canonical_root(root)
    resolved = _canonical_candidate(base, candidate)

    if resolved == base:
        if allow_root:
            return resolved
        raise PathEscape(base, candidate, "the root itself, not a path inside it")

    # normcase folds case on Windows and is the identity elsewhere; it is
    # applied to both sides or to neither, which is the whole point.
    try:
        common = os.path.commonpath([os.path.normcase(resolved), os.path.normcase(base)])
    except ValueError:
        # Different Windows drives, or mixed absolute/relative. Both mean the
        # candidate is not under the root.
        raise PathEscape(base, candidate) from None
    if common != os.path.normcase(base):
        raise PathEscape(base, candidate)
    return resolved
