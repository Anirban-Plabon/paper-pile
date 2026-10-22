from paper_pile.core.printdoc import (
    EmbedHtml,
    PrintAssets,
    PrintStyle,
    paper,
    print_page,
    render_print_body,
    text_width_mm,
)

BREAK = '<div style="page-break-after: always;"></div>'
ASSETS = PrintAssets("/k.css", "/p.css", "/p.js")


def test_every_block_carries_its_source_line() -> None:
    src = "# T\n\npara one\npara two\n\n- a\n- b\n\n```py\nx = 1\n```\n\n| a |\n|---|\n| 1 |\n"
    html = render_print_body(src, "n.md")
    assert '<h1 data-line="1">T</h1>' in html
    assert '<p data-line="3">para one<br />\npara two</p>' in html  # one <br> per source line
    assert '<li data-line="6">a</li>' in html and '<li data-line="7">b</li>' in html
    assert 'data-line="9" data-code-line="10"' in html  # the fence, its first code line
    assert '<tr data-line="15">' in html


def test_lines_count_from_the_top_of_the_file_and_front_matter_is_not_printed() -> None:
    html = render_print_body("---\ntitle: secret\n---\nbody\n", "n.md")
    assert html.strip() == '<p data-line="4">body</p>'


def test_display_math_keeps_its_line_and_tex() -> None:
    html = render_print_body("a\n\n$$\nx < 1\n$$\n", "n.md")
    assert '<div class="math block" data-line="3">x &lt; 1</div>' in html


def test_page_breaks_that_take_effect_are_kept() -> None:
    html = render_print_body(f"{BREAK}\n\na\n\n{BREAK}\n\nb\n\n{BREAK}\n", "n.md")
    assert html.count('class="pp-page-break"') == 1


def test_callouts_are_cards_like_in_the_editor() -> None:
    html = render_print_body("> **Warning:** careful\n\n> **Note:** x\n\n> plain\n", "n.md")
    assert 'class="pp-callout pp-callout-warn"' in html
    assert 'class="pp-callout"' in html
    assert html.count("<blockquote") == 3 and html.count('class="pp-callout') == 2


def test_vault_images_are_served_and_sized() -> None:
    html = render_print_body(
        "![pic|300](<.n.assets/p 1.png>)\n\n![w](https://x.org/y.png)\n", "d/n.md"
    )
    assert 'src="/_pp/asset?note=d%2Fn.md&amp;path=.n.assets%2Fp%201.png"' in html
    assert 'alt="pic"' in html and 'style="width: 300px"' in html
    assert 'src="https://x.org/y.png"' in html


def test_embed_lines_show_the_embedded_note() -> None:
    seen: list[tuple[str, str]] = []

    def embedder(target: str, heading: str) -> EmbedHtml:
        seen.append((target, heading))
        return (
            EmbedHtml("other › H", "<p>inside</p>")
            if target == "other"
            else EmbedHtml("x", "", "No note")
        )

    html = render_print_body(
        "a\n\n![[other#H]]\n\n![[gone]]\n\ntext ![[inline]]\n", "n.md", embedder
    )
    assert seen == [("other", "H"), ("gone", "")]
    assert '<div class="pp-embed" data-line="3">' in html and "<p>inside</p>" in html
    assert '<p class="pp-embed-missing">No note</p>' in html
    assert "![[inline]]" not in html  # an embed inside a text line stays a link


def test_note_html_stays_escaped() -> None:
    html = render_print_body("<script>alert(1)</script>\n\n<b>x</b>\n", "n.md")
    assert "<script" not in html and "<b>" not in html


def test_page_sets_paper_fonts_and_loads_the_layout_script() -> None:
    style = PrintStyle("Inter, sans-serif</style>", "Fira Code", 16, 1.5, (1, 2, 3))
    page = print_page("x", "n.md", title="A <b>", paper_name="Letter", style=style, assets=ASSETS)
    assert "<title>A &lt;b&gt;</title>" in page
    assert "@page { size: 215.9mm 279.4mm; margin: 0; }" in page
    assert "--pp-font: Inter, sans-serif/style;" in page  # no way out of the <style>
    assert "--pp-size: 16px; --pp-lh: 1.5;" in page and "--pp-accent-rgb: 1, 2, 3;" in page
    assert '<script type="module" src="/p.js"></script>' in page
    assert '<main id="pp-source">' in page


def test_paper_sizes() -> None:
    assert paper("A4").height_mm == 297 and paper("nonsense").name == "A4"
    assert text_width_mm("A4") == 170
    assert round(text_width_mm("Letter"), 1) == 175.9


def test_empty_lines_beyond_the_usual_gap_are_space() -> None:
    html = render_print_body("# H\n\n\n\npara\n\n- a\n\n\nend\n\n\n", "n.md")
    blanks = [line for line in html.splitlines() if "pp-blank" in line]
    assert blanks == [
        '<div class="pp-blank" data-line="3"></div>',
        '<div class="pp-blank" data-line="4"></div>',
        '<div class="pp-blank" data-line="9"></div>',
    ]  # trailing empty lines add nothing
    assert html.index('data-line="4"') < html.index('<p data-line="5">')


def test_empty_lines_before_the_first_block_are_all_space() -> None:
    html = render_print_body("---\nt: 1\n---\n\n\nbody\n", "n.md")
    assert html.count("pp-blank") == 2


def test_empty_lines_inside_blocks_are_left_to_the_block() -> None:
    assert "pp-blank" not in render_print_body("```\na\n\n\nb\n```\n", "n.md")
    assert "pp-blank" not in render_print_body("> a\n>\n>\n> b\n", "n.md")
