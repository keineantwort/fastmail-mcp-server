import contextvars

import pytest

from fastmail_mcp.oauth.scopes import get_scopes, require_scope, set_scopes


def _run_in_fresh_context(fn):
    """Run *fn* in a copy of the current context so contextvar changes don't leak."""
    ctx = contextvars.copy_context()
    return ctx.run(fn)


class TestSetAndGetScopes:
    def test_default_is_empty(self):
        def check():
            assert get_scopes() == set()

        _run_in_fresh_context(check)

    def test_roundtrip(self):
        def check():
            set_scopes({"mail.read", "mail.send"})
            assert get_scopes() == {"mail.read", "mail.send"}

        _run_in_fresh_context(check)


class TestRequireScope:
    def test_passes_when_granted(self):
        def check():
            set_scopes({"mail.read", "mail.send"})
            require_scope("mail.read")  # should not raise

        _run_in_fresh_context(check)

    def test_raises_when_missing(self):
        def check():
            set_scopes({"mail.read"})
            with pytest.raises(PermissionError, match="mail.send"):
                require_scope("mail.send")

        _run_in_fresh_context(check)

    def test_raises_with_empty_scopes(self):
        def check():
            with pytest.raises(PermissionError):
                require_scope("anything")

        _run_in_fresh_context(check)
