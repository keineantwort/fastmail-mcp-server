from fastmail_mcp.utils.quote_cleaner import clean_quoted_text


class TestCleanQuotedText:
    def test_plain_text_unchanged(self):
        body = "Hey, just following up on the meeting."
        assert clean_quoted_text(body) == body

    def test_removes_on_wrote_block(self):
        body = (
            "Sounds good, let's do it.\n\n"
            "On Mon, Jan 6, 2025 at 10:00 AM Alice <alice@example.com> wrote:\n"
            "> Sure, I think that works.\n"
            "> Let me know."
        )
        assert clean_quoted_text(body) == "Sounds good, let's do it."

    def test_removes_chevron_quoted_lines(self):
        body = "Thanks!\n> previous message\n>> even older"
        assert clean_quoted_text(body) == "Thanks!"

    def test_removes_original_message_separator(self):
        body = (
            "Got it.\n\n"
            "--- Original Message ---\n"
            "From: bob@example.com\n"
            "Some old content."
        )
        assert clean_quoted_text(body) == "Got it."

    def test_removes_forwarded_message_separator(self):
        body = (
            "FYI see below.\n\n"
            "--- Forwarded Message ---\n"
            "From: carol@example.com\n"
            "Forwarded content."
        )
        assert clean_quoted_text(body) == "FYI see below."

    def test_removes_outlook_style_header(self):
        body = (
            "Will do.\n\n"
            "From: Dave <dave@example.com>\n"
            "Sent: Monday, January 6, 2025\n"
            "To: Eve <eve@example.com>\n"
            "Subject: Re: Plans\n"
            "Old content here."
        )
        assert clean_quoted_text(body) == "Will do."

    def test_empty_string(self):
        assert clean_quoted_text("") == ""

    def test_only_quoted_text(self):
        body = "> This is all quoted.\n>> Deeply quoted."
        assert clean_quoted_text(body) == ""
