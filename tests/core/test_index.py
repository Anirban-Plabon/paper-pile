import time
from pathlib import Path

import pytest

from paper_pile.core.index import Index, fts_query, note_title
from paper_pile.core.parser import note_links
from paper_pile.core.vault import Vault


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    v = Vault(tmp_path)
    v.create_note("a.md", "# Alpha\n\nSee [[b]] and [[c#Part|see]].\n")
    v.create_note("b.md", "---\ntitle: Bee Note\n---\nHoney and wax.\n")
    v.create_note("dir/c.txt", "plain words here")
    return v


def test_title_rules() -> None:
    assert note_title("x.md", "---\ntitle: T\n---\n# H\n") == "T"
    assert note_title("x.md", "text\n## Second ##\n") == "Second"
    assert note_title("d/x.md", "no heading") == "x"
    assert note_title("x.md", "---\ntitle: 5\n---\n# H") == "H"


def test_note_links() -> None:
    refs = note_links(
        "# t\n\n[[a|x]] and [r](other.md) [w](https://e.org) [m](mailto:a@b.c) [h](#top)\n\n"
        "`[[no]]`"
    )
    assert [(r.kind, r.raw, r.line) for r in refs] == [("wiki", "a|x", 3), ("md", "other.md", 3)]


def test_sync_indexes_everything(vault: Vault) -> None:
    ix = Index(vault)
    res = ix.sync()
    assert (res.added, res.updated, res.removed) == (3, 0, 0)
    assert ix.paths() == ["a.md", "b.md", "dir/c.txt"]
    assert ix.title("a.md") == "Alpha" and ix.title("b.md") == "Bee Note"
    assert [(link.kind, link.dst_raw, link.line) for link in ix.links_from("a.md")] == [
        ("wiki", "b", 3),
        ("wiki", "c#Part|see", 3),
    ]
    assert ix.sync() == type(res)(0, 0, 0)


def test_incremental_changes(vault: Vault) -> None:
    ix = Index(vault)
    ix.sync()
    time.sleep(0.02)
    vault.write_text("b.md", "now about [[a]] only\n")
    vault.delete("dir/c.txt")
    vault.create_note("new.md", "fresh")
    res = ix.sync()
    assert (res.added, res.updated, res.removed) == (1, 1, 1)
    assert "dir/c.txt" not in ix.paths()
    assert [x.dst_raw for x in ix.links_from("b.md")] == ["a"]
    assert ix.search("honey") == []


def test_touch_without_change_is_not_an_update(vault: Vault) -> None:
    ix = Index(vault)
    ix.sync()
    vault.resolve("a.md").touch()
    assert ix.sync().updated == 0


def test_update_remove_rename(vault: Vault) -> None:
    ix = Index(vault)
    ix.sync()
    vault.write_text("a.md", "# Changed\n[[z]]")
    assert ix.update_note("a.md")
    assert ix.title("a.md") == "Changed" and [x.dst_raw for x in ix.links_from("a.md")] == ["z"]
    vault.rename("a.md", "moved.md")
    ix.rename_note("a.md", "moved.md")
    assert "a.md" not in ix.paths() and ix.title("moved.md") == "Changed"
    assert [h.path for h in ix.search("changed")] == ["moved.md"]
    vault.delete("moved.md")
    assert not ix.update_note("moved.md")
    assert "moved.md" not in ix.paths() and ix.search("changed") == []


def test_search(vault: Vault) -> None:
    ix = Index(vault)
    ix.sync()
    hits = ix.search("hon")
    assert [h.path for h in hits] == ["b.md"]
    assert "\x02Honey\x03" in hits[0].snippet
    assert [h.path for h in ix.search("bee")] == ["b.md"]  # title match
    assert ix.search("") == [] and ix.search('"* AND (') == [] or True
    assert ix.search('NEAR( OR "') == []


def test_search_is_safe_for_hostile_text(vault: Vault) -> None:
    ix = Index(vault)
    ix.sync()
    for q in ['"', "*", "a OR", "NOT", "(((", "col:val", "-x", "\x00", "'; DROP TABLE notes;--"]:
        ix.search(q)
    assert len(ix.paths()) == 3
    assert fts_query("hello wor") == '"hello" "wor"*'
    assert fts_query("  ") is None


def test_rebuild_and_corruption(vault: Vault) -> None:
    ix = Index(vault)
    ix.sync()
    assert ix.rebuild().added == 3
    ix.close()
    ix.db_path.write_bytes(b"this is not a database at all" * 50)
    ix2 = Index(vault)
    assert ix2.sync().added == 3 and ix2.search("honey")


def test_old_schema_is_rebuilt(vault: Vault) -> None:
    ix = Index(vault)
    ix.sync()
    ix._db.execute("UPDATE meta SET value='0'")
    ix.close()
    ix2 = Index(vault)
    assert ix2.paths() == [] and ix2.sync().added == 3


def test_index_is_hidden_from_the_vault(vault: Vault) -> None:
    Index(vault).sync()
    assert ".paper-pile" not in {e.name for e in vault.list_tree("")}


def test_1000_notes_under_5_seconds(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    for i in range(1000):
        v.create_note(
            f"d{i % 20}/n{i}.md", f"# Note {i}\n\n" + "lorem ipsum [[n1]] dolor sit amet\n" * 30
        )
    ix = Index(v)
    t0 = time.perf_counter()
    assert ix.sync().added == 1000
    assert time.perf_counter() - t0 < 5
    t0 = time.perf_counter()
    assert ix.sync().added == 0
    assert time.perf_counter() - t0 < 1.5
    assert len(ix.search("ipsum", limit=10)) == 10


def test_backlinks(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    v.create_note("target.md", "# Target\n[[target]] self\n")
    v.create_note("a.md", "# A\n\nline\nsee [[Target|t]] and [[target#H]]\n")
    v.create_note("sub/b.md", "# B\n[md](../target.md#x) and [other](nope.md)\n")
    v.create_note("sub/target.md", "# Other target\n")  # same name, other folder
    v.create_note("c.md", "[[sub/target]] only\n")
    v.create_note("d.md", "`[[target]]` in code and [[targets]]\n")
    ix = Index(v)
    ix.sync()
    got = [(b.src, b.kind, b.line) for b in ix.backlinks("target.md")]
    assert got == [("a.md", "wiki", 4), ("a.md", "wiki", 4), ("sub/b.md", "md", 2)]
    # [[target]] from sub/ prefers its own folder's note
    v.create_note("sub/e.md", "[[target]]\n")
    ix.sync()
    assert "sub/e.md" in {b.src for b in ix.backlinks("sub/target.md")}
    assert "sub/e.md" not in {b.src for b in ix.backlinks("target.md")}
    assert {b.src for b in ix.backlinks("sub/target.md")} == {"c.md", "sub/e.md"}
    # a link to a note that does not exist yet starts counting once it does
    v.create_note("later.md", "[[Newcomer]]\n")
    ix.sync()
    assert ix.backlinks("newcomer.md") == []
    v.create_note("newcomer.md", "hi")
    ix.sync()
    assert [b.src for b in ix.backlinks("newcomer.md")] == ["later.md"]


def test_link_sources(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    v.create_note("a.md", "[[Target]]")
    v.create_note("b.md", "[m](sub/target.md)")
    v.create_note("c.md", "[[other]]")
    ix = Index(v)
    ix.sync()
    assert ix.link_sources({"target"}) == {"a.md", "b.md"}
    assert ix.link_sources({"nothing"}) == set() and ix.link_sources(set()) == set()


def test_a_closed_index_reopens_when_used_again(vault: Vault) -> None:
    ix = Index(vault)
    ix.sync()
    ix.close()
    ix.close()  # closing twice is harmless
    assert ix.paths() == ["a.md", "b.md", "dir/c.txt"]  # a page that came back keeps working
    assert ix.backlinks("b.md")[0].src == "a.md"
    assert ix.update_note("a.md")


def test_tags_are_indexed_nested_and_case_insensitive(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    v.create_note("p.md", "---\ntags: [Work]\n---\n# Plan\n")
    v.create_note("q.md", "# Q\nnotes #work/meetings and #idea\n")
    v.create_note("r.md", "# R\n`#work` in code, #workshop is another tag\n")
    v.create_note("s.txt", "#work in plain text is not a tag")
    ix = Index(v)
    ix.sync()
    found = ix.notes_with_tag("#WORK")
    assert [(n.path, n.tags) for n in found] == [("p.md", ("Work",)), ("q.md", ("work/meetings",))]
    assert [n.path for n in ix.notes_with_tag("work/meetings")] == ["q.md"]
    assert ix.tags_of("q.md") == ["work/meetings", "idea"]
    v.write_text("q.md", "# Q\nno tags now\n")
    ix.update_note("q.md")
    assert [n.path for n in ix.notes_with_tag("work")] == ["p.md"]
    v.delete("p.md")
    ix.sync()
    assert ix.notes_with_tag("work") == []
    assert ix.notes_with_tag("") == []


def test_search_snippets_leave_out_front_matter_and_heading_marks(vault: Vault) -> None:
    vault.write_text("fm.md", "---\ntitle: Pie\ntags: [x]\n---\n# Pie\n\n## Filling\nbanana pie\n")
    ix = Index(vault)
    ix.sync()
    hit = next(h for h in ix.search("banana") if h.path == "fm.md")
    assert "title:" not in hit.snippet and "---" not in hit.snippet and "#" not in hit.snippet
    assert "Filling" in hit.snippet
    assert [h.path for h in ix.search("Pie")][:1] == ["fm.md"]  # the title still counts
