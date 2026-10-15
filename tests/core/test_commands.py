import pytest

from paper_pile.core.commands import (
    REGISTRY,
    Action,
    Command,
    CommandContext,
    CommandRegistry,
    Insert,
    ReplaceLinePrefix,
    UnknownCommandError,
    command,
    groups_json,
    match_score,
    push_recent,
)
from paper_pile.core.session import SessionState, load_session, save_session

CTX = CommandContext("a.md", "hello world", 5, selection=(0, 5))


def make() -> CommandRegistry:
    reg = CommandRegistry()

    def add(cid: str, title: str, group: str, **kw: object) -> None:
        command(cid, title, group=group, registry=reg, **kw)(  # type: ignore[arg-type]
            lambda ctx, cid=cid: Insert(cid)  # type: ignore[misc]
        )

    add("h1", "Heading 1", "Basic blocks", hint="#", aliases=["title", "heading"])
    add("h2", "Heading 2", "Basic blocks", hint="##", aliases=["subtitle", "heading"])
    add("todo", "To-do list", "Basic blocks", aliases=["checkbox", "task"])
    add("code", "Code block", "Code & math", aliases=["snippet"])
    add("math", "Math block", "Code & math", aliases=["latex"])
    add("date", "Date", "Insert")
    add("sum", "Summarize", "AI", when=lambda ctx: bool(ctx.selection))
    return reg


def names(groups: list) -> list[tuple[str, list[str]]]:  # type: ignore[type-arg]
    return [(g.name, [c.id for c in g.commands]) for g in groups]


def test_decorator_registers_and_runs() -> None:
    reg = CommandRegistry()

    @command("h2", "Heading 2", group="Basic blocks", hint="##", registry=reg)
    def h2(ctx: CommandContext) -> Action:
        return ReplaceLinePrefix("## ")

    assert reg.run("h2", CTX) == ReplaceLinePrefix("## ")
    assert h2(CTX) == ReplaceLinePrefix("## ")  # the function is returned unchanged
    with pytest.raises(UnknownCommandError):
        reg.run("nope", CTX)
    with pytest.raises(ValueError):
        command("h2", "again", group="x", registry=reg)(h2)


def test_default_registry_exists() -> None:
    assert isinstance(REGISTRY, CommandRegistry)


def test_match_score_ordering() -> None:
    texts = ["head", "heading", "sub heading", "the headline", "forehead", "hxexad"]
    s = {k: match_score("head", k) for k in texts}
    assert s["head"] == 100 and s["heading"] == 90 and s["sub heading"] == 75
    assert s["the headline"] == 75 and s["forehead"] == 60  # word start beats substring
    assert s["hxexad"] is not None and s["hxexad"] < 60  # letters in order only
    assert match_score("hd", "heading") is not None  # letters in order
    assert match_score("dh", "heading") is None
    assert match_score("", "anything") == 0
    assert match_score("  H1 ", "h1") == 100


def test_no_query_lists_everything_in_group_order() -> None:
    reg = make()
    assert names(reg.search("", CTX)) == [
        ("Basic blocks", ["h1", "h2", "todo"]),
        ("Code & math", ["code", "math"]),
        ("Insert", ["date"]),
        ("AI", ["sum"]),
    ]


def test_availability_hides_commands() -> None:
    reg = make()
    no_selection = CommandContext("a.md", "x", 0)
    assert "AI" not in [g.name for g in reg.search("", no_selection)]
    with pytest.raises(UnknownCommandError):
        reg.run("sum", no_selection)
    assert reg.run("sum", CTX) == Insert("sum")
    assert any(c.id == "sum" for c in reg.all())  # no context: nothing is hidden


def test_query_matches_title_alias_and_id() -> None:
    reg = make()
    assert names(reg.search("latex")) == [("Code & math", ["math"])]  # alias
    assert names(reg.search("todo"))[0][1][0] == "todo"  # id (title is "To-do list")
    assert names(reg.search("to-do"))[0][1][0] == "todo"
    assert reg.search("zzzz") == []  # empty groups are hidden: nothing at all


def test_query_ranks_best_first_and_groups_follow() -> None:
    reg = make()
    got = names(reg.search("head"))
    assert got == [("Basic blocks", ["h1", "h2"])]
    got = names(reg.search("code"))
    assert got[0] == ("Code & math", ["code"])


def test_alias_ranks_below_title() -> None:
    reg = CommandRegistry()
    command("a", "Heading", group="G", registry=reg)(lambda ctx: Insert("a"))
    command("b", "Other", group="G", aliases=["heading"], registry=reg)(lambda ctx: Insert("b"))
    assert names(reg.search("heading")) == [("G", ["a", "b"])]


def test_recents_float_to_top_without_a_query() -> None:
    reg = make()
    got = names(reg.search("", CTX, recents=["date", "h2", "gone"]))
    assert got[0] == ("Recent", ["date", "h2"])  # most recent first; unknown ids ignored
    assert ("Insert", ["date"]) not in got  # shown once, not twice
    assert got[1] == ("Basic blocks", ["h1", "todo"])


def test_recents_break_ties_with_a_query() -> None:
    reg = make()
    assert names(reg.search("heading"))[0][1] == ["h1", "h2"]
    assert names(reg.search("heading", recents=["h2"]))[0][1] == ["h2", "h1"]


def test_recents_are_capped_and_deduplicated() -> None:
    r: list[str] = []
    for cid in ["a", "b", "c", "a", "d", "e", "f"]:
        r = push_recent(r, cid)
    assert r == ["f", "e", "d", "a", "c"]
    reg = make()
    many = ["h1", "h2", "todo", "code", "math", "date"]
    assert len(reg.search("", CTX, recents=many)[0].commands) == 5


def test_json_for_the_editor() -> None:
    reg = make()
    data = groups_json(reg.search("h1"))
    assert data == [
        {
            "group": "Basic blocks",
            "items": [
                {
                    "id": "h1",
                    "title": "Heading 1",
                    "subtitle": "",
                    "badge": "",
                    "group": "Basic blocks",
                    "icon": "",
                    "hint": "#",
                }
            ],
        }
    ]


def test_context_selected_text() -> None:
    assert CTX.selected_text == "hello"
    assert CommandContext("a.md", "x", 0).selected_text == ""


def test_command_dataclass_is_frozen() -> None:
    cmd = make().get("h1")
    assert isinstance(cmd, Command)
    with pytest.raises(AttributeError):
        cmd.title = "x"  # type: ignore[misc]


def test_recents_persist_in_the_session(tmp_path) -> None:  # type: ignore[no-untyped-def]
    save_session(tmp_path, SessionState(recent_commands=["h1", "date"]))
    assert load_session(tmp_path).recent_commands == ["h1", "date"]
    (tmp_path / ".paper-pile" / "session.json").write_text('{"recent_commands": [1, "x", null]}')
    assert load_session(tmp_path).recent_commands == ["x"]
    (tmp_path / ".paper-pile" / "session.json").write_text('{"recent_commands": "oops"}')
    assert load_session(tmp_path).recent_commands == []
