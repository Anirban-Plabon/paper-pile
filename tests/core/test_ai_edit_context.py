"""P26.3: what the model sees of a note for an AI edit (PLAN §4.29)."""

from paper_pile.core.ai.blocks import block_map
from paper_pile.core.ai.context import estimate_tokens
from paper_pile.core.ai.edit_context import (
    EditBudget,
    item_key,
    key_terms,
    note_view,
    related_blocks,
    vault_view,
)

OPTIONS = """# Hosting

We compare three options for hosting the app.

- **Docker**: one container
- **VM**: a whole machine
- **Bare metal**: no layer at all

## Cost

| Option | Price |
|---|---|
| Docker | 0 |
| VM | 5 |
| Bare metal | 40 |

## Unrelated

The weather was nice when we wrote this.

## Summary

Docker is the easiest of the options.
"""


def ids_of(note: str, *starts: str) -> list[str]:
    blocks = block_map(note)
    return [next(b.id for b in blocks if b.text(note).startswith(s)) for s in starts]


def test_item_keys() -> None:
    assert item_key("- **Docker**: one container") == "docker"
    assert item_key("| Bare metal | 40 |") == "bare metal"
    assert item_key("1. [[Fly io|Fly]] is new") == "fly io"
    assert item_key("- [ ] plain words here and more") == "plain words here and"


def test_adding_an_option_finds_every_place_that_lists_them() -> None:
    blocks = block_map(OPTIONS)
    (target,) = ids_of(OPTIONS, "- **Bare metal**")
    terms = key_terms("add option D: Fly.io, a hosted platform", "- **Bare metal**")
    found = set(related_blocks(blocks, OPTIONS, [target], terms))
    intro, docker, table, summary = ids_of(
        OPTIONS, "We compare", "- **Docker**", "| Option", "Docker is the easiest"
    )
    assert {intro, docker, table, summary} <= found  # count, own list, same items, mentions
    (weather,) = ids_of(OPTIONS, "The weather")
    assert weather not in found


def test_the_view_shows_related_in_full_and_the_rest_as_outline() -> None:
    blocks = block_map(OPTIONS)
    (target,) = ids_of(OPTIONS, "- **Bare metal**")
    view = note_view(OPTIONS, blocks, [target], "add option D: Fly.io", EditBudget.for_window(8192))
    assert view.fits and view.full[0] == target
    assert "| VM | 5 |" in view.text  # the table in full
    assert "[B1] # Hosting" in view.text and "# Summary" in view.text  # headings always
    assert "The weather was nice" in view.text  # short notes: an outline line per block


def test_the_view_fits_small_windows_and_never_drops_the_target() -> None:
    body = "\n\n".join(f"## Part {n}\n\n" + f"Filler sentence {n} " * 30 for n in range(60))
    note = "# Big\n\n" + body + "\n\n## Target\n\nThe text to change.\n"
    blocks = block_map(note)
    (target,) = ids_of(note, "The text to change")
    for window in (4096, 8192, 32768):
        budget = EditBudget.for_window(window)
        view = note_view(note, blocks, [target], "make it formal", budget)
        assert "The text to change." in view.text
        outline = view.text.replace(f"[{target}] paragraph\nThe text to change.", "")
        assert estimate_tokens(outline) <= budget.outline + budget.related
    small = note_view(note, blocks, [target], "x", EditBudget.for_window(4096))
    assert small.folded > 0 and '1 block under "Part 0"' in small.text


def test_a_target_over_its_budget_does_not_fit() -> None:
    note = "# A\n\n" + "word " * 4000 + "\n"
    blocks = block_map(note)
    view = note_view(note, blocks, ["B2"], "rewrite", EditBudget.for_window(8192))
    assert not view.fits


def test_vault_hits_are_labelled_and_cut() -> None:
    text = vault_view([("x.md", "Options", "a " * 2000), ("y.md", "", "short")], 200)
    assert text.startswith("[V1] x.md § Options\n") and "[V2] y.md\nshort" in text
    assert estimate_tokens(text) < 260
    assert vault_view([], 100) == ""
