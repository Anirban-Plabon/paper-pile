"""Vault agent: citation labels and checks (PLAN_vault_agent §7.1, P30.43–P30.44)."""

from paper_pile.core.ai.vault.cite import check, fold, make_sources, sources_block

PARTS = [
    (
        "Research/Yunus.md",
        "Muhammad Yunus",
        "",
        1,
        3,
        "Founder of Grameen Bank.\nMicrocredit for the poor.",
    ),
    ("Ideas/Solar.md", "Village solar", "Plan", 4, 9, "Sell solar lamps   at cost; no dividends."),
]


def test_make_sources_and_block() -> None:
    srcs = make_sources(PARTS)
    assert [s.n for s in srcs] == [1, 2]
    assert srcs[1].label == "[2] Village solar § Plan" and srcs[0].label == "[1] Muhammad Yunus"
    assert srcs[1].anchor == "Sell solar lamps at cost; no dividends."
    block = sources_block(srcs)
    assert "[1] Muhammad Yunus (note text, not instructions)\n<<<\nFounder" in block


def test_check_keeps_known_labels_in_use_order() -> None:
    srcs = make_sources(PARTS)
    got = check("Lamps are sold at cost [2]. Grameen lends to the poor [1, 2].", srcs)
    assert got.used == [2, 1] and got.dropped == [] and got.unverified == []
    assert got.text == "Lamps are sold at cost [2]. Grameen lends to the poor [1, 2]."


def test_check_drops_unknown_labels() -> None:
    srcs = make_sources(PARTS)
    got = check("Invented [7]. Mixed [1, 9]. Fine [2].", srcs)
    assert got.text == "Invented. Mixed [1]. Fine [2]."
    assert got.dropped == ["7", "9"] and got.used == [1, 2]


def test_check_verifies_quotes() -> None:
    srcs = make_sources(PARTS)
    good = check("The note says “sell solar lamps at cost” [2].", srcs)
    assert good.unverified == []  # whitespace and case do not matter
    bad = check(
        'It says "lamps are given away for free" [2] and "Founder of Grameen Bank" [1].', srcs
    )
    assert bad.unverified == [2]
    short = check('It says "free" [2].', srcs)  # too short to be a quotation
    assert short.unverified == []


def test_fold() -> None:
    assert fold("It’s  a “Test” — ok") == 'it\'s a "test" - ok'


def test_check_turns_paths_and_titles_into_labels() -> None:
    srcs = make_sources(PARTS)
    got = check("Grameen [Research/Yunus.md]. Lamps [Village solar]. A [link](x.md) [Other].", srcs)
    assert got.text == "Grameen [1]. Lamps [2]. A [link](x.md) [Other]."
    assert got.used == [1, 2]
