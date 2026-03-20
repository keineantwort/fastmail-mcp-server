"""Tests for the allowlist → denylist label filter logic."""

import pytest

from fastmail_mcp.tools.email_tools import _is_allowed, _resolve_label_ids


# --- _resolve_label_ids ---


class TestResolveLabelIds:
    def test_empty_allowlist_returns_empty_set(self, monkeypatch):
        monkeypatch.setattr("fastmail_mcp.tools.email_tools.settings.allowlist_labels", [])
        monkeypatch.setattr("fastmail_mcp.tools.email_tools.settings.denylist_label", "Denylist")

        mailboxes = {"m1": "Inbox", "m2": "Denylist", "m3": "Projects"}
        allow, deny = _resolve_label_ids(mailboxes)

        assert allow == set()
        assert deny == {"m2"}

    def test_allowlist_resolves_matching_labels(self, monkeypatch):
        monkeypatch.setattr(
            "fastmail_mcp.tools.email_tools.settings.allowlist_labels", ["Inbox", "Projects"]
        )
        monkeypatch.setattr("fastmail_mcp.tools.email_tools.settings.denylist_label", "Denylist")

        mailboxes = {"m1": "Inbox", "m2": "Denylist", "m3": "Projects", "m4": "Archive"}
        allow, deny = _resolve_label_ids(mailboxes)

        assert allow == {"m1", "m3"}
        assert deny == {"m2"}

    def test_unknown_allowlist_label_ignored(self, monkeypatch):
        monkeypatch.setattr(
            "fastmail_mcp.tools.email_tools.settings.allowlist_labels", ["NonExistent"]
        )
        monkeypatch.setattr("fastmail_mcp.tools.email_tools.settings.denylist_label", "Denylist")

        mailboxes = {"m1": "Inbox", "m2": "Denylist"}
        allow, deny = _resolve_label_ids(mailboxes)

        assert allow == set()
        assert deny == {"m2"}

    def test_no_denylist_mailbox_returns_empty_deny(self, monkeypatch):
        monkeypatch.setattr("fastmail_mcp.tools.email_tools.settings.allowlist_labels", ["Inbox"])
        monkeypatch.setattr("fastmail_mcp.tools.email_tools.settings.denylist_label", "Denylist")

        mailboxes = {"m1": "Inbox", "m2": "Projects"}
        allow, deny = _resolve_label_ids(mailboxes)

        assert allow == {"m1"}
        assert deny == set()


# --- _is_allowed ---


class TestIsAllowed:
    """Test the two-stage filter: allowlist first, then denylist."""

    def test_no_allowlist_no_denylist_allows_all(self):
        assert _is_allowed({"m1"}, allowlist_ids=set(), denylist_ids=set()) is True

    def test_no_allowlist_not_on_denylist_allows(self):
        assert _is_allowed({"m1"}, allowlist_ids=set(), denylist_ids={"m2"}) is True

    def test_no_allowlist_on_denylist_blocks(self):
        assert _is_allowed({"m1", "m2"}, allowlist_ids=set(), denylist_ids={"m2"}) is False

    def test_on_allowlist_not_on_denylist_allows(self):
        assert _is_allowed({"m1"}, allowlist_ids={"m1"}, denylist_ids={"m2"}) is True

    def test_not_on_allowlist_blocks(self):
        assert _is_allowed({"m3"}, allowlist_ids={"m1", "m2"}, denylist_ids=set()) is False

    def test_on_allowlist_and_denylist_blocks(self):
        """Mail with both an allowed and a denied label must be blocked (denylist wins)."""
        assert _is_allowed({"m1", "m2"}, allowlist_ids={"m1"}, denylist_ids={"m2"}) is False

    def test_spec_example(self):
        """Verify the exact example from the spec:

        Allowlist: A (m1), B (m2)
        Denylist: C (m3)
        Mail 1 => A           → allowed
        Mail 2 => B           → allowed
        Mail 3 => A, C        → blocked
        Mail 4 => B, C        → blocked
        """
        allow = {"m1", "m2"}  # A, B
        deny = {"m3"}  # C

        assert _is_allowed({"m1"}, allow, deny) is True  # Mail 1
        assert _is_allowed({"m2"}, allow, deny) is True  # Mail 2
        assert _is_allowed({"m1", "m3"}, allow, deny) is False  # Mail 3
        assert _is_allowed({"m2", "m3"}, allow, deny) is False  # Mail 4

    def test_mail_without_any_labels_blocked_when_allowlist_set(self):
        assert _is_allowed(set(), allowlist_ids={"m1"}, denylist_ids=set()) is False

    def test_mail_without_any_labels_allowed_when_no_allowlist(self):
        assert _is_allowed(set(), allowlist_ids=set(), denylist_ids={"m2"}) is True


# --- Config tests for the new settings ---


class TestLabelSettings:
    def test_defaults(self, monkeypatch):
        monkeypatch.setenv("FASTMAIL_API_TOKEN", "tok_test")
        monkeypatch.setenv("AUTHENTIK_URL", "https://auth.example.com")
        from fastmail_mcp.config import Settings

        s = Settings(_env_file=None)
        assert s.allowlist_labels == []
        assert s.denylist_label == "Denylist"

    def test_custom_labels(self, monkeypatch):
        monkeypatch.setenv("FASTMAIL_API_TOKEN", "tok_test")
        monkeypatch.setenv("AUTHENTIK_URL", "https://auth.example.com")
        monkeypatch.setenv("ALLOWLIST_LABELS", '["AI-Allowed","Projects"]')
        monkeypatch.setenv("DENYLIST_LABEL", "Blocked")
        from fastmail_mcp.config import Settings

        s = Settings(_env_file=None)
        assert s.allowlist_labels == ["AI-Allowed", "Projects"]
        assert s.denylist_label == "Blocked"
