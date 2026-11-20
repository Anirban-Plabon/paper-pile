"""The formatting menu's items (PLAN §4.38): ids, labels, icons and groups, and which are pinned.

The menu (Ask box button, right-click on a selection) shows the pinned items first — five by
default, the user picks them (``editor.format_pinned``) — then every item by group. What an item
does to the text is :mod:`paper_pile.core.formatting`; the edit items (cut, copy, paste) and
alignment are the editor's own. Data only: no UI here.
"""

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FormatItem:
    id: str
    label: str
    icon: str  # a Lucide icon name
    group: str
    asks: str = ""  # what the item needs first: "color" | "link" | "comment" | ""
    hint: str = ""  # the markdown it writes, or its shortcut


ITEMS: tuple[FormatItem, ...] = (
    FormatItem("highlight", "Highlight", "highlighter", "Text", hint="==text=="),
    FormatItem("comment", "Comment", "message-square-plus", "Text", asks="comment"),
    FormatItem("underline", "Underline", "underline", "Text", hint="<u>"),
    FormatItem("color", "Text colour", "palette", "Text", asks="color"),
    FormatItem("link", "Link", "link", "Text", asks="link", hint="[text](url)"),
    FormatItem("bold", "Bold", "bold", "Text", hint="**text**"),
    FormatItem("italic", "Italic", "italic", "Text", hint="*text*"),
    FormatItem("strike", "Strikethrough", "strikethrough", "Text", hint="~~text~~"),
    FormatItem("code", "Inline code", "code", "Text", hint="`text`"),
    FormatItem("quote", "Quote", "quote", "Blocks", hint=">"),
    FormatItem("bullet", "Bulleted list", "list", "Blocks", hint="-"),
    FormatItem("numbered", "Numbered list", "list-ordered", "Blocks", hint="1."),
    FormatItem("todo", "To-do list", "square-check", "Blocks", hint="[ ]"),
    FormatItem("h1", "Heading 1", "heading-1", "Blocks", hint="#"),
    FormatItem("h2", "Heading 2", "heading-2", "Blocks", hint="##"),
    FormatItem("h3", "Heading 3", "heading-3", "Blocks", hint="###"),
    FormatItem("align-left", "Align left", "text-align-start", "Alignment"),
    FormatItem("align-center", "Align center", "text-align-center", "Alignment"),
    FormatItem("align-right", "Align right", "text-align-end", "Alignment"),
    FormatItem("align-justify", "Justify", "text-align-justify", "Alignment"),
    FormatItem("cut", "Cut", "scissors", "Edit", hint="Ctrl+X"),
    FormatItem("copy", "Copy", "copy", "Edit", hint="Ctrl+C"),
    FormatItem("paste", "Paste", "clipboard-paste", "Edit", hint="Ctrl+V"),
    FormatItem("delete", "Delete", "trash-2", "Edit", hint="Del"),
)

BY_ID: dict[str, FormatItem] = {item.id: item for item in ITEMS}
GROUPS: tuple[str, ...] = tuple(dict.fromkeys(item.group for item in ITEMS))
DEFAULT_PINNED: tuple[str, ...] = ("highlight", "comment", "underline", "color", "link")
MAX_PINNED = 8
EDIT_ITEMS = frozenset({"cut", "copy", "paste", "delete"})
ALIGN_ITEMS = frozenset({"align-left", "align-center", "align-right", "align-justify"})


def pinned_items(raw: object) -> list[str]:
    """The pinned ids from a setting's value: known ids only, each once, at most
    :data:`MAX_PINNED`; anything unreadable gives the defaults. An empty list stays empty
    (the user unpinned everything)."""
    if not isinstance(raw, list | tuple):
        return list(DEFAULT_PINNED)
    out: list[str] = []
    for value in raw:
        if isinstance(value, str) and value in BY_ID and value not in out:
            out.append(value)
    return out[:MAX_PINNED]


def toggle_pinned(pinned: Iterable[str], item_id: str) -> list[str]:
    """Pin ``item_id`` (at the end) or unpin it. Past :data:`MAX_PINNED` nothing is added."""
    current = [i for i in pinned if i in BY_ID]
    if item_id in current:
        return [i for i in current if i != item_id]
    if item_id not in BY_ID or len(current) >= MAX_PINNED:
        return current
    return [*current, item_id]


def grouped(exclude: Iterable[str] = ()) -> list[tuple[str, list[FormatItem]]]:
    """Every item by group (in menu order), without ``exclude``."""
    skip = set(exclude)
    out: list[tuple[str, list[FormatItem]]] = []
    for group in GROUPS:
        items = [i for i in ITEMS if i.group == group and i.id not in skip]
        if items:
            out.append((group, items))
    return out
