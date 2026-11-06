"""Chat mentions: how a picked note goes into the box and how a sent message shows them."""

from paper_pile.gui.components.chat import mention_html, mention_text


def test_a_one_word_name_goes_in_without_brackets() -> None:
    assert mention_text("test") == "@test"
    assert mention_text("31-Oct-2026") == "@31-Oct-2026"
    assert mention_text("Projects/plan") == "@Projects/plan"
    # spaces become no-break spaces: it looks the same and stays one mention (no [[ ]])
    assert mention_text("AI in Education") == "@AI\xa0in\xa0Education"
    assert mention_text("odd [x]") == "@[[odd [x]]]"
    assert mention_text("v1.") == "@[[v1.]]"  # a closing dot would be read as punctuation


def test_a_sent_message_shows_mentions_in_the_accent_without_brackets() -> None:
    shown = mention_html("compare @[[my note]] with @test, and @Daily/ <b>")
    assert shown == (
        'compare <span class="pp-at">@my note</span> with <span class="pp-at">@test</span>, '
        'and <span class="pp-at">@Daily/</span> &lt;b&gt;'
    )
    assert mention_html("mail me@x.com") == "mail me@x.com"


def test_a_name_with_no_break_spaces_is_one_mention() -> None:
    from paper_pile.core.ai.context import extract_mentions

    text = "compare @AI\xa0in\xa0Education, and @test please"
    assert extract_mentions(text) == ["AI in Education", "test"]
    assert '<span class="pp-at">@AI\xa0in\xa0Education</span>,' in mention_html(text)
