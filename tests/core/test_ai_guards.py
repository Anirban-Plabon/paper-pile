"""P26.6: the checks on every AI change, G1–G9 (PLAN §4.29)."""

from paper_pile.core.ai.guards import GuardContext, change_share, check, main_script

PARA = "We compare three options. See [[Plan]] and run `make up` at https://x.org."


def kinds(issues):  # type: ignore[no-untyped-def]
    return [(i.kind, i.severity) for i in issues]


def test_g1_a_title_the_selection_did_not_have_is_removed() -> None:
    ctx = GuardContext("change", "rewrite it")
    new, issues = check(ctx, PARA, "## Options\n\n" + PARA.replace("compare", "weigh"))
    assert new.startswith("We weigh") and kinds(issues) == [("heading", "fixed")]
    _, issues = check(ctx, PARA, PARA + "\n\n## More\n\ntext")
    assert ("heading", "retry") in kinds(issues)
    asked = GuardContext("change", "add a heading to it")
    assert check(asked, PARA, "## Options\n\n" + PARA)[0].startswith("## Options")


def test_g1_headings_in_the_target_keep_their_levels() -> None:
    old = "Intro.\n\n### Sub\n\nBody."
    ctx = GuardContext("change", "make it formal", size="large")
    assert check(ctx, old, "Intro text.\n\n### Sub\n\nBody text.")[1] == []
    _, issues = check(ctx, old, "Intro.\n\n## Sub\n\nBody.")
    assert issues[0].feedback.startswith("Keep the headings exactly as they are (level 3)")


def test_g1_new_sections_and_new_text() -> None:
    section = GuardContext("add_after", "add backups", new_section=True, level=2)
    assert check(section, "", "## Backups\n\nNightly.\n\n### How\n\nCopy.")[1] == []
    assert kinds(check(section, "", "Nightly.")[1]) == [("heading", "retry")]
    assert kinds(check(section, "", "## A\n\nx\n\n## B\n\ny")[1]) == [("heading", "retry")]
    para = GuardContext("add_after", "add a sentence")
    new, issues = check(para, "", "# Note\n\nOne more sentence.")
    assert new == "One more sentence." and kinds(issues) == [("heading", "fixed")]


def test_g3_tokens_kept_unless_asked_to_remove() -> None:
    ctx = GuardContext("change", "make it formal", size="large")
    _, issues = check(ctx, PARA, "We weigh three options. See the plan and run make up.")
    assert kinds(issues) == [("tokens", "retry")]
    assert "[[Plan]]" in issues[0].feedback and "`make up`" in issues[0].feedback
    unlink = GuardContext("change", "remove the link to [[Plan]]", size="large")
    _, issues = check(unlink, PARA, PARA.replace("See [[Plan]] and run", "Run"))
    assert issues == []
    translate = GuardContext("change", "Bengali", size="large", translate=True)
    old = "Read [[Plan|the plan]]."
    assert check(translate, old, "পড়ুন [[Plan|পরিকল্পনা]]।")[1] == []


def test_g5_size_against_the_request() -> None:
    assert change_share("a b c d", "a b c d") == 0.0 and change_share("a", "b") == 1.0
    small = GuardContext("change", "fix grammar", size="small")
    fixed = "We compare three option. See [[Plan]] and run `make up` at https://x.org."
    assert check(small, PARA, fixed)[1] == []
    rewritten = "Three choices are weighed here. See [[Plan]]; `make up` at https://x.org runs."
    issues = check(small, PARA, rewritten)[1]
    assert kinds(issues) == [("size", "retry")] and "small fixes" in issues[0].message
    assert kinds(check(small, PARA, rewritten, retried=True)[1]) == [("size", "warn")]


def test_g6_g7_g9() -> None:
    before = "The paragraph before it, as context."
    ctx = GuardContext("change", "x", size="large", neighbours=(before,))
    _, issues = check(ctx, "- a\n- b", "a and b")
    assert kinds(issues) == [("kind", "warn")]
    new, issues = check(ctx, "Old text.", before + "\n\nNew text.")
    assert new == "New text." and kinds(issues) == [("echo", "fixed")]
    assert main_script("Hello world") == "LATIN" and main_script("আমার সোনার বাংলা") == "BENGALI"
    _, issues = check(ctx, "আমার সোনার বাংলা", "My golden Bengal")
    assert ("language", "warn") in kinds(issues)


def test_g6_no_warning_for_the_kind_that_was_asked_for() -> None:
    quote = GuardContext("change", "put it in quote", size="large")
    assert kinds(check(quote, "Some text.", "> Some text.")[1]) == []
    bullets = GuardContext("change", "this as a bullet list", size="large")
    assert kinds(check(bullets, "a and b", "- a\n- b")[1]) == []


def test_g5_a_few_typos_in_a_short_sentence_are_a_small_fix() -> None:
    small = GuardContext("change", "fix grammar", size="small")
    typos = "Teh backup runs evry night and it were fast."
    assert change_share(typos, "The backup runs every night and it was fast.") > 0.2
    assert check(small, typos, "The backup runs every night and it was fast.")[1] == []
    issues = check(small, typos, "Our nightly job copies all data quickly.")[1]
    assert kinds(issues) == [("size", "retry")]  # a rewrite is still too much for a fix
