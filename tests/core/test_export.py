import base64
from pathlib import Path

from paper_pile.core.export import export_html, export_markdown
from paper_pile.core.vault import Vault

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 24


def _vault(tmp_path: Path) -> Vault:
    (tmp_path / "notes" / ".a.assets").mkdir(parents=True)
    (tmp_path / "notes" / ".a.assets" / "p.png").write_bytes(PNG)
    return Vault(tmp_path)


def test_markdown_inlines_vault_images_only(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    text = "# A\n\n![pic|300](.a.assets/p.png)\n\n![web](https://x.org/y.png)\n\n![gone](.a.assets/no.png)\n"
    out = export_markdown(vault, "notes/a.md", text)
    uri = "data:image/png;base64," + base64.b64encode(PNG).decode()
    assert f"![pic|300]({uri})" in out
    assert "![web](https://x.org/y.png)" in out
    assert "![gone](.a.assets/no.png)" in out  # missing: left alone
    assert out.startswith("# A\n")


def test_markdown_without_images_is_unchanged(tmp_path: Path) -> None:
    text = "---\ntitle: A\n---\nplain [[link]]\n"
    assert export_markdown(_vault(tmp_path), "notes/a.md", text) == text


def test_html_is_one_page_with_inlined_images_and_no_scripts(tmp_path: Path) -> None:
    text = "# Title <x>\n\n![p](.a.assets/p.png)\n"
    out = export_html(_vault(tmp_path), "notes/a.md", text, "a <b>")
    assert out.startswith("<!doctype html>")
    assert "<title>a &lt;b&gt;</title>" in out
    assert "<h1>Title &lt;x&gt;</h1>" in out
    assert 'src="data:image/png;base64,' in out
    assert "<script" not in out


def test_page_breaks_print_in_html_and_stay_in_markdown(tmp_path: Path) -> None:
    text = 'a\n\n<div style="page-break-after: always;"></div>\n\nb\n'
    vault = _vault(tmp_path)
    html = export_html(vault, "notes/a.md", text, "a")
    assert '<div class="pp-page-break"></div>' in html
    assert ".pp-page-break { break-after: page;" in html
    assert "&lt;div" not in html
    assert export_markdown(vault, "notes/a.md", text) == text
