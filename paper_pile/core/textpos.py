"""Text offsets: Python counts code points, the browser counts UTF-16 units. They differ for
characters outside the basic plane (emoji, some CJK), so offsets crossing the boundary are
converted here."""


def utf16_index(text: str, index: int) -> int:
    """``index`` (code points into ``text``) as a JavaScript string offset."""
    return len(text[:index].encode("utf-16-le", "surrogatepass")) // 2


def codepoint_index(text: str, offset: int) -> int:
    """A JavaScript string ``offset`` (UTF-16 units) as an index into ``text``. An offset that
    points into the middle of a surrogate pair rounds down to the character's start."""
    units = 0
    for i, ch in enumerate(text):
        if units >= offset:
            return i
        units += 2 if ord(ch) > 0xFFFF else 1
        if units > offset:
            return i
    return len(text)
