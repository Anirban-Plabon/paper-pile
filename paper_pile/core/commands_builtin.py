"""The built-in slash commands. Importing this module registers them on the default registry.

P4.2 ships the *Basic blocks* group; the rest of the phase-1 list (code/math, diagrams, media,
links, insert, AI) arrives with P4.3 and later tasks. Icons are Material icon names.
"""

from paper_pile.core.commands import (
    Action,
    CommandContext,
    Insert,
    ReplaceLinePrefix,
    command,
)

BASIC = "Basic blocks"

# (id, title, icon, hint, line prefix, aliases)
_LINE_BLOCKS = [
    ("text", "Text", "notes", "", "", ("paragraph", "plain")),
    ("h1", "Heading 1", "looks_one", "#", "# ", ("heading", "title", "header")),
    ("h2", "Heading 2", "looks_two", "##", "## ", ("heading", "subtitle", "header")),
    ("h3", "Heading 3", "looks_3", "###", "### ", ("heading", "header")),
    ("h4", "Heading 4", "looks_4", "####", "#### ", ("heading", "header")),
    ("bullet", "Bulleted list", "format_list_bulleted", "-", "- ", ("ul", "list", "unordered")),
    ("numbered", "Numbered list", "format_list_numbered", "1.", "1. ", ("ol", "list", "ordered")),
    ("todo", "To-do list", "check_box", "[ ]", "- [ ] ", ("checkbox", "task", "checklist")),
    ("quote", "Quote", "format_quote", ">", "> ", ("blockquote", "cite")),
]


def _line_block(
    cid: str, title: str, icon: str, hint: str, prefix: str, aliases: tuple[str, ...]
) -> None:
    @command(cid, title, group=BASIC, icon=icon, hint=hint, aliases=aliases)
    def run(ctx: CommandContext) -> Action:
        return ReplaceLinePrefix(prefix)


for _spec in _LINE_BLOCKS:
    _line_block(*_spec)


@command(
    "divider",
    "Divider",
    group=BASIC,
    icon="horizontal_rule",
    hint="---",
    aliases=("hr", "rule", "line", "separator"),
)
def divider(ctx: CommandContext) -> Action:
    """A horizontal rule. Directly under a text line ``---`` would make that line a heading, so
    a blank line goes first unless there already is one."""
    line_start = ctx.text.rfind("\n", 0, ctx.cursor) + 1
    previous = ctx.text[: line_start - 1].rsplit("\n", 1)[-1] if line_start else ""
    return Insert("\n---\n" if previous.strip() else "---\n")
