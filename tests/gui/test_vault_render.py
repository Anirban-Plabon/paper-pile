"""Citation pills in vault answers (PLAN_vault_agent §7.1, P30.45)."""

from paper_pile.gui.vault_render import cite_pills, cite_tip

CITES = [
    {"n": 1, "path": "R/Yunus.md", "title": "Yunus", "heading": "", "anchor": "Founder of Grameen"},
    {"n": 2, "path": "R/Bank.md", "title": "Bank", "heading": "Plan", "anchor": ""},
]


def test_cite_tip() -> None:
    assert cite_tip(CITES[0]) == "Yunus — “Founder of Grameen”"
    assert cite_tip(CITES[1]) == "Bank § Plan"


def test_pills_replace_known_labels_only() -> None:
    html = "<p>A [1]. B [1, 2]. C [7].</p><pre><code>x = a[1]</code></pre><p>D <code>[2]</code></p>"
    out = cite_pills(html, CITES, 4)
    assert out.count('class="pp-cite"') == 3  # [1], [1, 2] → 3 pills; [7] unknown
    assert 'data-turn="4" data-n="2" data-tip="Bank § Plan">2</a>' in out
    assert "C [7]." in out  # an unknown number stays text
    assert "<pre><code>x = a[1]</code></pre>" in out  # code untouched
    assert "<code>[2]</code>" in out


def test_pills_escape_the_tip_and_ignore_tags() -> None:
    cites = [{"n": 1, "title": 'He said "hi" <b>', "anchor": ""}]
    out = cite_pills('<p title="[1]">See [1]</p>', cites, 0)
    assert 'title="[1]"' in out  # inside a tag: not a label
    assert 'data-tip="He said &quot;hi&quot; &lt;b&gt;"' in out
    assert cite_pills("<p>[1]</p>", [], 0) == "<p>[1]</p>"
