"""P26.5: tokens an AI edit must keep, and fixed blocks set aside (PLAN §4.29)."""

from paper_pile.core.ai.protect import mask, missing_tokens, protected_tokens, unmask

TEXT = (
    "See [[Hosting plan|the plan]] and ![[img.png]], run `npm i`, where $x^2$ grows. "
    "Read [the docs](https://x.org/a) or https://y.org. #infra #team/ops [^1] "
    "<kbd>Ctrl</kbd> <!-- note --> costs $5 and $10 ^block-1"
)


def test_tokens_are_found_once_each() -> None:
    assert protected_tokens(TEXT) == [
        "[[Hosting plan|the plan]]",
        "![[img.png]]",
        "`npm i`",
        "$x^2$",
        "https://x.org/a",
        "https://y.org",
        "#infra",
        "#team/ops",
        "[^1]",
        "<kbd>",
        "</kbd>",
        "<!-- note -->",
        "^block-1",
    ]
    assert protected_tokens("Issue #12 and C# or a#b") == []  # not tags
    assert protected_tokens("`a #tag inside`") == ["`a #tag inside`"]


def test_missing_tokens() -> None:
    new = TEXT.replace("|the plan]]", "|our plan]]").replace("`npm i`", "npm i")
    assert missing_tokens(TEXT, new) == ["[[Hosting plan|the plan]]", "`npm i`"]
    assert missing_tokens(TEXT, TEXT + "\nmore") == []
    assert missing_tokens("a #tag", "a", allowed=["#tag"]) == []
    assert missing_tokens("[[a]] [[a]]", "[[a]]") == ["[[a]]"]  # each one counts


def test_mask_and_unmask() -> None:
    text = "Before\n\n```py\nx = 1\n```\n\nMiddle\n\n$$\ny\n$$\n\nAfter"
    a = text.index("```")
    b = text.index("```", a + 3) + 3
    c = text.index("$$")
    d = text.index("$$", c + 2) + 2
    masked, kept = mask(text, [(c, d), (a, b)])
    assert masked == "Before\n\n⟦KEEP 1⟧\n\nMiddle\n\n⟦KEEP 2⟧\n\nAfter"
    assert unmask(masked.replace("Middle", "Centre"), kept) == (
        text.replace("Middle", "Centre"),
        [],
    )
    assert unmask("⟦KEEP 1⟧ x", kept)[1] == [1, 2]  # not on its own line, and 2 is gone
    assert unmask("⟦KEEP 1⟧\n⟦KEEP 1⟧\n⟦KEEP 2⟧", kept)[1] == [1]  # twice
