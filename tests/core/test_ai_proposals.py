"""AI edits as proposals (PLAN §4.26): line hunks, accept / reject, out-of-date detection."""

from paper_pile.core.ai.proposals import accept, apply_changes, locate, propose, reject

NOTE = "# Title\n\nline one\nline two\nline three\n\nend\n"


def region() -> tuple[int, int]:
    start = NOTE.index("line one")
    return start, NOTE.index("\nend")


def test_hunks_are_the_changed_lines() -> None:
    start, end = region()
    p = propose("a.md", NOTE, start, end, "line one\nline 2\nline three\nline four\n")
    assert p is not None
    assert [(h.old, h.new) for h in p.hunks] == [("line two\n", "line 2\n"), ("", "line four\n")]
    two = p.hunks[0]
    assert NOTE[two.start : two.end] == "line two\n"
    assert propose("a.md", NOTE, start, end, NOTE[start:end]) is None


def test_accept_all_gives_the_new_text() -> None:
    start, end = region()
    new = "line one\nline 2\nline three\nline four\n"
    p = propose("a.md", NOTE, start, end, new)
    assert p is not None
    result = accept(p, NOTE)
    assert result is not None
    changes, left = result
    assert left is None and apply_changes(NOTE, changes) == NOTE[:start] + new + NOTE[end:]


def test_accept_one_then_the_other_matches_accept_all() -> None:
    start, end = region()
    new = "LINE ONE\nline two\nline three\nadded\n"
    p = propose("a.md", NOTE, start, end, new)
    assert p is not None and len(p.hunks) == 2
    first = accept(p, NOTE, {p.hunks[0].id})
    assert first is not None
    changes, left = first
    text = apply_changes(NOTE, changes)
    assert left is not None and len(left.hunks) == 1
    assert text[left.start : left.end] == left.old  # the region follows the accepted change
    second = accept(left, text)
    assert second is not None and second[1] is None
    assert apply_changes(text, second[0]) == NOTE[:start] + new + NOTE[end:]


def test_typing_above_moves_it_typing_inside_makes_it_out_of_date() -> None:
    start, end = region()
    p = propose("a.md", NOTE, start, end, "line one\nline 2\nline three\n")
    assert p is not None
    moved = locate(p, "extra words\n" + NOTE)
    assert moved is not None and moved.start == p.start + len("extra words\n")
    changed = NOTE.replace("line two", "line too")
    assert locate(p, changed) is None and accept(p, changed) is None
    twice = NOTE + NOTE[start:end]
    assert locate(p, "x" + twice) is None  # moved, and now found twice: ambiguous


def test_reject() -> None:
    start, end = region()
    p = propose("a.md", NOTE, start, end, "LINE ONE\nline two\nline three\nadded\n")
    assert p is not None
    one = reject(p, p.hunks[0].id)
    assert one is not None and [h.new for h in one.hunks] == ["added\n"]
    assert reject(one, one.hunks[0].id) is None and reject(p) is None


def test_selection_without_line_break_keeps_lines() -> None:
    text = "Teh cat sat.\nNext line\n"
    p = propose("a.md", text, 0, 12, "The cat sat.")
    assert p is not None and [(h.old, h.new) for h in p.hunks] == [("Teh cat sat.", "The cat sat.")]
    result = accept(p, text)
    assert result is not None and apply_changes(text, result[0]) == "The cat sat.\nNext line\n"
