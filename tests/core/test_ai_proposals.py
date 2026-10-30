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
    rest = left.regions[0]
    assert text[rest.start : rest.end] == rest.old  # the region follows the accepted change
    second = accept(left, text)
    assert second is not None and second[1] is None
    assert apply_changes(text, second[0]) == NOTE[:start] + new + NOTE[end:]


def test_typing_above_moves_it_typing_inside_makes_it_out_of_date() -> None:
    start, end = region()
    p = propose("a.md", NOTE, start, end, "line one\nline 2\nline three\n")
    assert p is not None
    moved = locate(p, "extra words\n" + NOTE)
    assert moved is not None
    assert moved.regions[0].start == p.regions[0].start + len("extra words\n")
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


MANY = "# Hosting\n\nWe compare three options.\n\n- Docker\n- VM\n\n## Cost\n\nCheap.\n"


def test_one_proposal_for_several_places() -> None:
    from paper_pile.core.ai.issues import Issue
    from paper_pile.core.ai.proposals import Edit, propose_many, stale_hunks

    count = MANY.index("three")
    vm = MANY.index("- VM") + len("- VM")
    warn = Issue("tokens", "warn", "Lost: x")
    p = propose_many(
        "a.md",
        MANY,
        [
            Edit(vm, vm, "\n- Fly.io", "add the option", outside=False),
            Edit(count, count + 5, "four", "update the count", (warn,), outside=True),
        ],
    )
    assert p is not None and len(p.regions) == 2
    assert [(h.old, h.new, h.reason) for h in p.hunks] == [
        ("We compare three options.\n", "We compare four options.\n", "update the count"),
        ("", "- Fly.io\n", "add the option"),
    ]
    assert p.hunks[0].outside and p.hunks[0].issues == (warn,) and not p.hunks[1].outside
    done = accept(p, MANY)
    assert done is not None and done[1] is None
    assert apply_changes(MANY, done[0]) == MANY.replace("three", "four").replace(
        "- VM\n", "- VM\n- Fly.io\n"
    )
    # the user changed the intro meanwhile: that region is out of date, the other still applies
    typed = MANY.replace("We compare", "Here we compare")
    assert stale_hunks(p, typed) == {p.hunks[0].id}
    part = accept(p, typed)
    assert part is not None and apply_changes(typed, part[0]).count("- Fly.io") == 1
    assert accept(p, typed, {p.hunks[0].id}) is None  # only the stale one: nothing applied


def test_accepting_one_place_moves_the_others() -> None:
    from paper_pile.core.ai.proposals import Edit, propose_many

    count = MANY.index("three")
    cheap = MANY.index("Cheap.")
    p = propose_many(
        "a.md",
        MANY,
        [Edit(count, count + 5, "three (or four)"), Edit(cheap, cheap + 6, "Cheap enough.")],
    )
    assert p is not None
    first = accept(p, MANY, {p.hunks[0].id})
    assert first is not None and first[1] is not None
    text = apply_changes(MANY, first[0])
    region = first[1].regions[0]
    assert text[region.start : region.end] == region.old == "Cheap.\n"
    second = accept(first[1], text)
    assert second is not None and apply_changes(text, second[0]).endswith("Cheap enough.\n")


def test_word_marks() -> None:
    from paper_pile.core.ai.proposals import word_marks

    marks = word_marks("We compare three options.", "We compare four options.")
    assert marks == ([(11, 16)], [(11, 15)])
    assert word_marks("one two three", "four five six") is None  # all changed: no marks


def test_relocate_moves_and_drops_regions() -> None:
    from paper_pile.core.ai.proposals import Edit, propose_many, relocate

    count, cheap = MANY.index("three"), MANY.index("Cheap.")
    p = propose_many("a.md", MANY, [Edit(count, count + 5, "four"), Edit(cheap, cheap + 6, "Low.")])
    assert p is not None
    moved, lost = relocate(p, "New first line.\n" + MANY)
    assert moved is not None and lost == 0
    assert moved.regions[0].start == p.regions[0].start + len("New first line.\n")
    gone, lost = relocate(p, MANY.replace("Cheap.", "Costly."))
    assert gone is not None and lost == 1 and len(gone.regions) == 1
    assert relocate(p, "")[0] is None
