"""Strip quoted text from email bodies to reduce token usage."""

import re

# Patterns matching common quote indicators
_QUOTE_PATTERNS = [
    # "On <date>, <person> wrote:" style headers
    re.compile(r"^On .+ wrote:\s*$", re.MULTILINE),
    # "> " prefixed lines (standard quoting)
    re.compile(r"^>+.*$", re.MULTILINE),
    # "--- Original Message ---" separators
    re.compile(r"^-{2,}\s*(Original|Forwarded)\s+Message\s*-{2,}.*", re.MULTILINE | re.IGNORECASE),
    # "From: ..." header in forwarded messages
    re.compile(
        r"^From:\s+.+\nSent:\s+.+\nTo:\s+.+\nSubject:\s+.+",
        re.MULTILINE | re.IGNORECASE,
    ),
]


def clean_quoted_text(body: str) -> str:
    """Remove quoted/forwarded text from an email body.

    Returns only the 'new' content of the email.
    """
    # First pass: find the earliest quote header and truncate
    for pattern in _QUOTE_PATTERNS:
        match = pattern.search(body)
        if match:
            body = body[: match.start()]

    # Second pass: remove any remaining > prefixed lines
    lines = body.splitlines()
    cleaned = [line for line in lines if not line.startswith(">")]

    return "\n".join(cleaned).strip()
