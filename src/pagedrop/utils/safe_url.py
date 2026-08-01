"""URL scheme allowlist for opening external links from untrusted PDF URIs."""

from __future__ import annotations

# Schemes safe to hand to the desktop opener after user confirm.
ALLOWED_OPEN_SCHEMES = frozenset({"http", "https", "mailto"})


def is_allowed_open_scheme(scheme: str) -> bool:
    """True when *scheme* may be passed to ``QDesktopServices.openUrl``."""
    return scheme.casefold() in ALLOWED_OPEN_SCHEMES
