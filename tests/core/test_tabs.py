import pytest

from paper_pile.core.tabs import TabList


def opened(*paths: str) -> TabList:
    tabs = TabList()
    for p in paths:
        tabs.open(p)
    return tabs


def test_open_appends_and_reuses_existing() -> None:
    tabs = TabList()
    a, created = tabs.open("a.md")
    assert created and tabs.paths == ["a.md"]
    b, created = tabs.open("d/b.md")
    assert created and tabs.paths == ["a.md", "d/b.md"]
    again, created = tabs.open("a.md")
    assert not created and again is a  # opening an open note never duplicates it
    assert tabs.paths == ["a.md", "d/b.md"]
    assert a.id != b.id


def test_open_does_not_activate_by_itself() -> None:
    tabs = opened("a.md")
    assert tabs.active is None


def test_ids_are_never_reused() -> None:
    tabs = TabList()
    first, _ = tabs.open("a.md")
    tabs.close(first.id)
    second, _ = tabs.open("a.md")
    assert second.id != first.id


def test_activate_unknown_raises() -> None:
    tabs = opened("a.md")
    with pytest.raises(KeyError):
        tabs.activate(999)
    tabs.activate(None)


def test_close_active_prefers_right_neighbour_then_left() -> None:
    tabs = opened("a.md", "b.md", "c.md")
    a, b, c = tabs.tabs
    tabs.activate(b.id)
    assert tabs.close(b.id) == c.id  # right neighbour
    assert tabs.paths == ["a.md", "c.md"]
    assert tabs.close(c.id) == a.id  # no right neighbour: left
    assert tabs.close(a.id) is None  # last one: nothing active
    assert tabs.paths == [] and tabs.active is None


def test_close_inactive_keeps_active() -> None:
    tabs = opened("a.md", "b.md", "c.md")
    a, b, c = tabs.tabs
    tabs.activate(c.id)
    assert tabs.close(a.id) == c.id
    assert tabs.active == c.id and tabs.paths == ["b.md", "c.md"]


def test_close_unknown_is_a_noop() -> None:
    tabs = opened("a.md")
    tabs.activate(tabs.tabs[0].id)
    assert tabs.close(999) == tabs.active
    assert tabs.paths == ["a.md"]


def test_move_before_and_after() -> None:
    tabs = opened("a.md", "b.md", "c.md", "d.md")
    a, b, c, d = tabs.tabs
    assert tabs.move(d.id, a.id, after=False)
    assert tabs.paths == ["d.md", "a.md", "b.md", "c.md"]
    assert tabs.move(d.id, c.id, after=True)
    assert tabs.paths == ["a.md", "b.md", "c.md", "d.md"]
    assert tabs.move(a.id, c.id, after=False)
    assert tabs.paths == ["b.md", "a.md", "c.md", "d.md"]


def test_move_noops() -> None:
    tabs = opened("a.md", "b.md")
    a, b = tabs.tabs
    assert not tabs.move(a.id, a.id, after=True)
    assert not tabs.move(a.id, b.id, after=False)  # already just before b
    assert not tabs.move(b.id, a.id, after=True)  # already just after a
    assert not tabs.move(999, a.id, after=True)
    assert not tabs.move(a.id, 999, after=True)
    assert tabs.paths == ["a.md", "b.md"]


def test_move_keeps_active() -> None:
    tabs = opened("a.md", "b.md", "c.md")
    a, b, c = tabs.tabs
    tabs.activate(b.id)
    tabs.move(a.id, c.id, after=True)
    assert tabs.active == b.id


def test_rename_note_and_folder_prefix() -> None:
    tabs = opened("old.md", "docs/a.md", "docs/deep/b.md", "docsx/c.md")
    changed = tabs.rename_prefix("old.md", "new.md")
    assert [t.path for t in changed] == ["new.md"]
    changed = tabs.rename_prefix("docs", "guides")
    assert sorted(t.path for t in changed) == ["guides/a.md", "guides/deep/b.md"]
    assert tabs.paths == [
        "new.md",
        "guides/a.md",
        "guides/deep/b.md",
        "docsx/c.md",
    ]  # docsx untouched
    assert tabs.rename_prefix("missing", "x") == []


def test_tab_keeps_its_id_and_position_across_rename() -> None:
    tabs = opened("a.md", "b.md")
    a, b = tabs.tabs
    tabs.activate(b.id)
    tabs.rename_prefix("b.md", "z.md")
    assert tabs.get(b.id).path == "z.md"  # type: ignore[union-attr]
    assert tabs.active == b.id and tabs.paths == ["a.md", "z.md"]


def test_under() -> None:
    tabs = opened("a.md", "d/b.md", "d/e/c.md", "dd/x.md")
    assert sorted(t.path for t in tabs.under("d")) == ["d/b.md", "d/e/c.md"]
    assert [t.path for t in tabs.under("a.md")] == ["a.md"]
    assert tabs.under("zzz") == []


def test_cycle_wraps_both_ways() -> None:
    tabs = opened("a.md", "b.md", "c.md")
    a, b, c = tabs.tabs
    tabs.activate(a.id)
    assert tabs.cycle(1) == b.id
    tabs.activate(c.id)
    assert tabs.cycle(1) == a.id  # wraps forward
    tabs.activate(a.id)
    assert tabs.cycle(-1) == c.id  # wraps backward
    assert TabList().cycle(1) is None
    tabs.active = None
    assert tabs.cycle(1) == a.id  # nothing active: start at the first


def test_titles_disambiguate_only_duplicates() -> None:
    tabs = opened("notes/readme.md", "docs/readme.md", "todo.md", "readme.md")
    titles = tabs.titles()
    by_path = {t.path: titles[t.id] for t in tabs.tabs}
    assert by_path["todo.md"] == ("todo.md", None)
    assert by_path["notes/readme.md"] == ("readme.md", "notes")
    assert by_path["docs/readme.md"] == ("readme.md", "docs")
    assert by_path["readme.md"] == ("readme.md", "/")  # root folder shown as "/"


def test_pinned_tabs_come_first() -> None:
    tabs = opened("a", "b", "c", "d")
    ids = {t.path: t.id for t in tabs.tabs}
    assert tabs.set_pinned(ids["c"], True)
    assert tabs.paths == ["c", "a", "b", "d"]
    assert tabs.set_pinned(ids["d"], True)
    assert tabs.paths == ["c", "d", "a", "b"]  # joins the end of the pinned group
    assert not tabs.set_pinned(ids["d"], True)  # already pinned
    assert tabs.set_pinned(ids["c"], False)
    assert tabs.paths == ["d", "c", "a", "b"]  # first of the unpinned ones
    tabs.open("e")
    assert tabs.paths[-1] == "e"


def test_a_drag_never_mixes_pinned_and_unpinned() -> None:
    tabs = opened("a", "b", "c")
    ids = {t.path: t.id for t in tabs.tabs}
    tabs.set_pinned(ids["a"], True)
    tabs.move(ids["c"], ids["a"], after=False)  # an unpinned tab dropped before a pinned one
    assert tabs.paths == ["a", "c", "b"]
    tabs.move(ids["a"], ids["b"], after=True)  # a pinned tab dropped among unpinned ones
    assert tabs.paths == ["a", "c", "b"]
    renamed = tabs.rename_prefix("a", "z")
    assert renamed[0].pinned
