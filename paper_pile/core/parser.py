"""Markdown parsing for everything that is not the editor: HTML rendering, link/outline
extraction (later tasks), AI chat replies, export.

One configured :class:`markdown_it.MarkdownIt` is the reference for what a note *means*:
CommonMark + GFM tables, strikethrough, task lists, footnotes, YAML front matter and
dollar math. The editor's own Lezer grammar (``tools/editor_src/math.js``) must agree with
the math rules below; ``tests/fixtures/math_cases.json`` is checked against both.

Math rules (the pandoc convention, as implemented by ``mdit_py_plugins.dollarmath``):

* ``$inline$``: no whitespace right after the opening ``$`` or right before the closing one,
  no digit directly before the opening or after the closing ``$`` (so ``$5 and $10`` is text),
  ``\\$`` is a literal dollar, content is not empty. The *first* unescaped closing ``$``
  decides: if it is invalid the opening ``$`` is plain text (no scanning further).
* ``$$inline$$`` inside a paragraph is allowed and has no whitespace rules.
* ``$$`` block: a line starting with ``$$`` (indent < 4) that closes on the same line
  (``$$x$$``) or on a later line ending in ``$$``. An unclosed block, or one with a blank
  line before its closing ``$$``, is plain text. A block may directly follow a paragraph line.

Raw HTML in notes is escaped, not passed through: rendered output is used in places that
must stay safe (chat replies, exports). Single newlines render as line breaks, matching what
the editor shows.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import yaml
from markdown_it import MarkdownIt
from markdown_it.rules_block import StateBlock
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.dollarmath.index import math_block_dollar
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

_PARAGRAPH_LIKE = ["paragraph", "reference", "blockquote", "list"]


def make_parser(*, breaks: bool = True) -> MarkdownIt:
    """A fresh configured parser (cheap; the module-level one below is shared)."""
    md = (
        MarkdownIt("commonmark", {"html": False, "breaks": breaks})
        .enable(["table", "strikethrough"])
        .use(footnote_plugin)
        .use(tasklists_plugin, enabled=True)
        .use(
            dollarmath_plugin,
            allow_labels=False,
            allow_space=False,
            allow_digits=False,
            allow_blank_lines=False,
            double_inline=True,
        )
    )
    md.block.ruler.before("table", "front_matter", _front_matter_rule)
    # let a `$$` block start right after a paragraph line (the plugin's own registration cannot)
    md.block.ruler.at("math_block", _interrupting_math_block(), {"alt": _PARAGRAPH_LIKE})
    return md


def _front_matter_rule(state: StateBlock, start: int, end: int, silent: bool) -> bool:
    """YAML front matter: only at the very top, opened by a line that is exactly ``---`` and
    closed by the next line that is exactly ``---``. Anything else is not front matter.

    (The plugin's own rule also accepts ``----`` openers, text after the dashes and a ``...``
    closer, which the editor grammar would have to copy; a plain rule is easier to keep in sync.)
    """
    if start != 0:
        return False
    lines = state.src.split("\n")
    if lines[0].rstrip() != "---":
        return False
    close = next((i for i in range(1, min(len(lines), end)) if lines[i].rstrip() == "---"), None)
    if close is None:
        return False  # unclosed: ordinary markdown
    if silent:
        return True
    token = state.push("front_matter", "", 0)
    token.hidden = True
    token.markup = "---"
    token.block = True
    token.content = state.getLines(1, close, 0, False)
    state.line = close + 1
    token.map = [0, state.line]
    return True


def _interrupting_math_block() -> Callable[[StateBlock, int, int, bool], bool]:
    """The plugin's block rule, made safe to use as a paragraph terminator.

    The plugin rule ignores ``silent`` and always emits a token and moves ``state.line``;
    called from a paragraph's terminator check that would duplicate blocks. In silent mode we
    run it, undo its side effects and only report whether a block starts here.
    """
    rule = math_block_dollar(allow_labels=False, allow_blank_lines=False)

    def wrapped(state: StateBlock, start: int, end: int, silent: bool) -> bool:
        if not silent:
            return rule(state, start, end, False)
        line, ntokens = state.line, len(state.tokens)
        found = rule(state, start, end, False)
        del state.tokens[ntokens:]
        state.line = line
        return found

    return wrapped


_PARSER = make_parser()


def render_html(text: str) -> str:
    """Render a note's markdown to HTML (front matter is dropped, math is left as spans)."""
    return str(_PARSER.render(text))


@dataclass(frozen=True, slots=True)
class FrontMatter:
    raw: str  # the YAML text between the --- lines
    data: dict[str, Any]  # parsed mapping; {} if the YAML is not a mapping
    error: str | None = None  # why parsing failed, if it did


def front_matter(text: str) -> FrontMatter | None:
    """The note's YAML front matter, or ``None`` if it has none."""
    tokens = _PARSER.parse(text)
    if not tokens or tokens[0].type != "front_matter":
        return None
    raw = tokens[0].content
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return FrontMatter(raw, {}, str(exc).splitlines()[0])
    if loaded is None:
        return FrontMatter(raw, {})
    if not isinstance(loaded, dict):
        return FrontMatter(raw, {}, "front matter is not a key: value mapping")
    return FrontMatter(raw, loaded)


def math_spans(text: str) -> tuple[list[str], list[str]]:
    """``(inline, block)`` math contents found in ``text``, in order. Used by the sync tests."""
    inline: list[str] = []
    block: list[str] = []

    def walk(tokens: list[Any]) -> None:
        for tok in tokens:
            if tok.type in ("math_inline", "math_inline_double"):
                inline.append(tok.content)
            elif tok.type == "math_block":
                block.append(tok.content.strip())
            if tok.children:
                walk(tok.children)

    walk(_PARSER.parse(text))
    return inline, block
