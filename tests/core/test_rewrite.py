import random

import pytest

from paper_pile.core.links import parse_wikilink, resolve_md_link, resolve_wikilink
from paper_pile.core.parser import link_spans
from paper_pile.core.rewrite import apply_edits, plan_rewrites


def run(files: dict[str, str], moves: dict[str, str]) -> tuple[dict[str, str], int, int]:
    """Apply ``moves`` to ``files`` (path -> text), rewrite; returns (files, updated, skipped)."""
    moved = {moves.get(p, p): t for p, t in files.items()}
    plan = plan_rewrites(moves, set(moved), moved)
    return {**moved, **plan.texts}, plan.updated, plan.skipped


def test_wikilinks_keep_alias_heading_embed_and_whitespace() -> None:
    files = {
        "a.md": (
            "[[Old]] [[Old|alias]] [[Old#Head]] [[Old#H|al]] ![[Old]] "
            "[[ Old ]] [[Old.md]] [[other]]"
        ),
        "Old.md": "# Old",
    }
    got, updated, skipped = run(files, {"Old.md": "New.md"})
    assert got["a.md"] == (
        "[[New]] [[New|alias]] [[New#Head]] [[New#H|al]] ![[New]] [[ New ]] [[New.md]] [[other]]"
    )
    assert (updated, skipped) == (7, 0)
    assert got["New.md"] == "# Old"


def test_markdown_links() -> None:
    files = {
        "a.md": '[x](old.md) [y](old.md#part) [z](<old.md> "t") [s](old.md "title") [o](other.md)',
        "sub/b.md": "[up](../old.md?x=1#h)",
        "old.md": "",
    }
    got, updated, _ = run(files, {"old.md": "dir/new name.md"})
    assert got["a.md"] == (
        '[x](dir/new%20name.md) [y](dir/new%20name.md#part) [z](<dir/new name.md> "t") '
        '[s](dir/new%20name.md "title") [o](other.md)'
    )
    assert got["sub/b.md"] == "[up](../dir/new%20name.md?x=1#h)"
    assert updated == 5


def test_nothing_else_is_touched() -> None:
    text = (
        "---\nlinks: [[Old]]\n---\n"
        "`[[Old]]` and [[Old]]\n\n```\n[[Old]] [x](old.md)\n```\n\n    [[Old]]\n\n"
        "<https://e.org/old.md> [w](https://e.org/old.md) [m](mailto:a@b.c) "
        "[[Ghost]] [g](ghost.md)\n"
    )
    got, updated, skipped = run(
        {"a.md": text, "Old.md": "", "t.txt": "[[Old]]"}, {"Old.md": "N.md"}
    )
    assert updated == 1 and skipped == 0
    assert got["a.md"] == text.replace("and [[Old]]", "and [[N]]")
    assert got["t.txt"] == "[[Old]]"  # plain text is never rewritten


def test_folder_move() -> None:
    files = {
        "top.md": "[[inner]] [r](f/inner.md) [[f/inner]] [[sib]]",
        "f/inner.md": "[[top]] [t](../top.md) [s](sib.md) [[sib]] [[#same]]",
        "f/sib.md": "",
    }
    moves = {"f/inner.md": "g/inner.md", "f/sib.md": "g/sib.md"}
    got, _, skipped = run(files, moves)
    assert got["top.md"] == "[[inner]] [r](g/inner.md) [[g/inner]] [[sib]]"
    # links between the two moved notes stay as they were; links out of the folder get fixed
    assert got["g/inner.md"] == "[[top]] [t](../top.md) [s](sib.md) [[sib]] [[#same]]"
    assert skipped == 0


def test_moved_note_relative_links_are_fixed() -> None:
    files = {"a/n.md": "[x](../b/t.md) [y](t2.md)", "b/t.md": "", "a/t2.md": ""}
    got, _, _ = run(files, {"a/n.md": "c/d/n.md"})
    assert got["c/d/n.md"] == "[x](../../b/t.md) [y](../../a/t2.md)"


def test_bare_name_that_would_be_hijacked_gets_a_path() -> None:
    files = {"src/s.md": "[[idea]]", "src/idea.md": "", "idea.md": "root"}
    # moving the root idea.md next to s.md would capture [[idea]] (same folder wins)
    got, updated, _ = run(files, {"src/idea.md": "elsewhere/idea.md", "idea.md": "src/idea.md"})
    assert updated == 1
    assert got["src/s.md"] == "[[elsewhere/idea]]"


def test_path_style_links_stay_path_style() -> None:
    got, _, _ = run({"a.md": "[[f/Old]]", "f/Old.md": ""}, {"f/Old.md": "g/h/Old.md"})
    assert got["a.md"] == "[[h/Old]]"


def test_crlf_and_containers_and_tables() -> None:
    text = "# T\r\n\r\n> - see [[Old|b]] and [x](old.md)\r\n\r\n| q [[Old]] |\r\n|--|\r\n"
    got, updated, skipped = run({"a.md": text, "Old.md": ""}, {"Old.md": "N.md"})
    assert got["a.md"] == text.replace("[[Old|b]]", "[[N|b]]").replace("[[Old]]", "[[N]]")
    assert updated == 2 and skipped == 0  # old.md does not exist, so that link is left alone


def test_md_links_in_containers() -> None:
    text = "> - see [x](old.md)\r\n\r\n| q |\r\n|--|\r\n| [m](old.md) |\r\n"
    got, updated, _ = run({"a.md": text, "old.md": ""}, {"old.md": "n.md"})
    assert got["a.md"] == text.replace("old.md", "n.md") and updated == 2


def test_duplicate_looking_links_on_a_line() -> None:
    text = "`[[Old]]` then [[Old]] and [[Old]]\n"
    got, updated, _ = run({"a.md": text, "Old.md": ""}, {"Old.md": "N.md"})
    assert got["a.md"] == "`[[Old]]` then [[N]] and [[N]]\n" and updated == 2


def test_unlocatable_link_is_skipped_not_guessed() -> None:
    # `\|` in a table cell: the parser sees `[[Old|x]]`, the file says `[[Old\|x]]`
    text = "| a |\n|--|\n| [[Old\\|x]] |\n"
    got, updated, skipped = run({"a.md": text, "Old.md": ""}, {"Old.md": "N.md"})
    assert got["a.md"] == text and updated == 0


def test_reference_style_links_are_skipped() -> None:
    text = "[t][r]\n\n[r]: old.md\n"
    got, updated, skipped = run({"a.md": text, "old.md": ""}, {"old.md": "n.md"})
    assert got["a.md"] == text and updated == 0 and skipped == 1


def test_round_trip_and_idempotence() -> None:
    files = {
        "a.md": "[[Old]] [[Old#h|x]] [m](Old.md) ![[Old]]\n> [[Old.md]]\n",
        "d/b.md": "[up](../Old.md#z) [[Old]] [[d/b]]\n",
        "Old.md": "own [[a]] [s](d/b.md)\n",
    }
    moves = {"Old.md": "x/Moved.md", "d/b.md": "e/b.md"}
    there, _, _ = run(files, moves)
    again = plan_rewrites({}, set(there), there)
    assert again.updated == 0  # idempotent: nothing left to fix
    back, _, _ = run(there, {v: k for k, v in moves.items()})
    assert back == files  # and moving back restores every byte


@pytest.mark.parametrize("seed", range(25))
def test_every_link_still_leads_to_the_same_note(seed: int) -> None:
    rng = random.Random(seed)
    folders = ["", "a/", "a/b/", "c/"]
    names = ["n1", "n2", "n3", "n4", "n5", "n6"]
    paths = sorted({rng.choice(folders) + rng.choice(names) + ".md" for _ in range(12)})
    forms = []
    for target in paths:
        stem = target[:-3]
        forms += [f"[[{stem.rsplit('/', 1)[-1]}]]", f"[[{stem}|al]]", f"[[{stem}#H]]"]
    files = {}
    for p in paths:
        files[p] = "\n".join(rng.sample(forms, 5)) + "\n"
        rel = [f"[l](/{p})"]  # absolute links are not note links; must stay untouched
        files[p] += rel[0] + "\n"
    old_set = set(paths)
    # random distinct moves into distinct free paths
    free = [f + n + ".md" for f in folders for n in names if f + n + ".md" not in old_set]
    rng.shuffle(free)
    movers = rng.sample(paths, min(3, len(paths)))
    moves = dict(zip(movers, free, strict=False))
    spans_before = {}
    for p, t in files.items():
        for s in link_spans(t):
            if s.kind == "wiki":
                parsed = parse_wikilink(s.raw)
                assert parsed
                spans_before[(p, s.source, s.line, s.line_offset)] = resolve_wikilink(
                    parsed.note, p, old_set
                )
    got, _, skipped = run(files, moves)
    assert skipped == 0
    new_set = set(got)
    for (p, source, line, _offset), old_target in spans_before.items():
        new_p = moves.get(p, p)
        if old_target is None:
            continue
        expected = moves.get(old_target, old_target)
        # find the link again at the same line/ordinal in the new text and resolve it
        found = [s for s in link_spans(got[new_p]) if s.line == line and s.kind == "wiki"]
        assert found, (p, source)
        results = {
            resolve_wikilink(parse_wikilink(s.raw).note, new_p, new_set)  # type: ignore[union-attr]
            for s in found
        }
        assert expected in results
    # untouched non-note links
    for p in paths:
        assert "[l](/" + p + ")" in got[moves.get(p, p)]
    assert resolve_md_link("x.md", "a.md", {"a.md"}) is None
    assert apply_edits("abc", []) == "abc"
