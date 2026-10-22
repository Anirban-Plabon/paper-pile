from paper_pile.core.merge import join_texts, plan_merge

PATHS = ["a/src.md", "b/dst.md", "a/other.md", "c/linker.md", "plain.txt"]


def test_join_texts() -> None:
    assert join_texts("one\n", "two\n") == "one\n\ntwo\n"
    assert join_texts("one\n\n\n", "\n\ntwo") == "one\n\ntwo\n"
    assert join_texts("", "two") == "two\n"
    assert join_texts("one\n", "\n") == "one\n"


def test_body_drops_front_matter_and_follows_the_move() -> None:
    source = "---\ntitle: src\n---\nSee [o](other.md) and [[other]].\n\n![p](.src.assets/x.png)\n"
    plan = plan_merge("a/src.md", "b/dst.md", source, "# Dst\n", PATHS, {})
    assert plan.text.startswith("# Dst\n\nSee [o](../a/other.md) and [[other]].")
    assert "![p](.dst.assets/x.png)" in plan.text  # images move to the target's folder
    assert "title: src" not in plan.text
    assert plan.skipped == 0


def test_links_to_the_source_point_at_the_target() -> None:
    others = {
        "c/linker.md": "x [[src]] y [s](../a/src.md#h) z [[dst]]\n",
        "a/other.md": "nothing here\n",
        "a/src.md": "[[src]]\n",  # the source itself is ignored here
    }
    target = "Self: [[src]]\n"
    plan = plan_merge("a/src.md", "b/dst.md", "body\n", target, PATHS, others)
    assert plan.updated == {"c/linker.md": "x [[dst]] y [s](../b/dst.md#h) z [[dst]]\n"}
    assert plan.text == "Self: [[dst]]\n\nbody\n"


def test_into_plain_text_appends_raw() -> None:
    plan = plan_merge("a/src.md", "plain.txt", "[[other]]\n", "x\n", PATHS, {})
    assert plan.text == "x\n\n[[other]]\n"
