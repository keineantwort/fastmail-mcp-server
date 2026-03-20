"""Scope checking via contextvars (RFC 8414 / RFC 9728 pattern)."""

import contextvars
from typing import NoReturn

# Holds the set of granted scopes for the current request
_current_scopes: contextvars.ContextVar[set[str]] = contextvars.ContextVar(
    "_current_scopes", default=set()
)


def set_scopes(scopes: set[str]) -> None:
    """Set the granted scopes for the current request context."""
    _current_scopes.set(scopes)


def get_scopes() -> set[str]:
    """Get the granted scopes for the current request context."""
    return _current_scopes.get()


def require_scope(scope: str) -> None | NoReturn:
    """Raise if the required scope is not granted in the current context."""
    granted = _current_scopes.get()
    if scope not in granted:
        raise PermissionError(f"Scope '{scope}' is required but not granted. Have: {granted}")
