"""The built-in slash commands. Importing this module registers them on the default registry.

Groups: Basic blocks, Code & math, Diagrams, Media (table now; image with P5), Links, Insert.
The AI group arrives with P7. Icons are Material icon names.
"""

from dataclasses import replace
from datetime import datetime

from paper_pile.core.commands import (
    Action,
    CommandContext,
    Insert,
    OpenPicker,
    ReplaceLinePrefix,
    StreamInsert,
    command,
)
from paper_pile.core.tables import Table, format_table
from paper_pile.core.templates import DATE_FORMAT, TIME_FORMAT

BASIC = "Basic blocks"

_BLOCK_LINES = {"bullet", "numbered", "todo", "quote"}

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
        # lists and quotes get an empty line after them, so they end and can be left
        return ReplaceLinePrefix(prefix, blank_after=cid in _BLOCK_LINES)


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


# ---- blocks that need their own lines ---------------------------------------------------------


def block(ctx: CommandContext, body: str, caret: int | None = None) -> Insert:
    """Insert a multi-line ``body`` as its own block: if the command was typed after other text on
    the line, the block starts on a fresh line, and an empty line follows it (unless one does, or
    the next line is part of the same quote), so the block can be left. ``caret`` is an offset
    into ``body``."""
    line_start = ctx.text.rfind("\n", 0, ctx.cursor) + 1
    lead = "\n" if ctx.text[line_start : ctx.cursor].strip() else ""
    rest = ctx.text[ctx.end if ctx.end is not None else ctx.cursor :]
    first_rest, _, below = rest.partition("\n")
    following = below.split("\n", 1)[0]
    gap = ""
    if body.endswith("\n"):
        # the block ends its own line; what is left of the typed line comes right after it, and
        # a line break straight after the block is already the empty line we want
        gap = "\n" if first_rest.strip() else ""
    elif not rest:
        gap = "\n"  # end of the note: leave a line below the block
    elif not first_rest.strip() and following.strip():
        same_quote = body.startswith(">") and following.lstrip().startswith(">")
        gap = "" if same_quote else "\n"
    text = lead + body + gap
    return Insert(text, len(lead) + (len(body) if caret is None else caret))


@command(
    "callout",
    "Callout",
    group=BASIC,
    icon="info",
    hint="> **",
    aliases=("note", "info", "admonition"),
)
def callout(ctx: CommandContext) -> Action:
    """A highlighted note. Plain quote + bold label, which Live Preview and every markdown
    renderer show properly (``> [!note]`` callouts would show as odd link text here)."""
    return block(ctx, "> **Note:** ")


CODE = "Code & math"


@command(
    "code", "Code block", group=CODE, icon="code", hint="```", aliases=("snippet", "pre", "fence")
)
def code_block(ctx: CommandContext) -> Action:
    return block(ctx, "```\n\n```\n", 4)


@command(
    "math",
    "Math block",
    group=CODE,
    icon="functions",
    hint="$$",
    aliases=("latex", "equation", "formula"),
)
def math_block(ctx: CommandContext) -> Action:
    return block(ctx, "$$\n\n$$\n", 3)


@command(
    "math-inline",
    "Inline math",
    group=CODE,
    icon="superscript",
    hint="$ $",
    aliases=("latex", "equation"),
)
def math_inline(ctx: CommandContext) -> Action:
    return Insert("$$", 1)


DIAGRAMS = "Diagrams"

_FLOWCHART = (
    "flowchart TD\n    A[Start] --> B{Decision}\n    B -->|Yes| C[Do it]\n    B -->|No| D[Skip]\n"
)
_SEQUENCE = "sequenceDiagram\n    Alice->>Bob: Hello\n    Bob-->>Alice: Hi there\n"
_GANTT = (
    "gantt\n    title Plan\n    dateFormat YYYY-MM-DD\n    section Work\n"
    "    First task :a1, 2026-01-01, 7d\n    Second task :after a1, 5d\n"
)


def _mermaid(cid: str, title: str, icon: str, source: str, aliases: tuple[str, ...]) -> None:
    @command(cid, title, group=DIAGRAMS, icon=icon, hint="mermaid", aliases=aliases)
    def run(ctx: CommandContext) -> Action:
        return block(ctx, f"```mermaid\n{source}```\n")


_mermaid("flowchart", "Flowchart", "account_tree", _FLOWCHART, ("mermaid", "diagram", "graph"))
_mermaid("sequence", "Sequence diagram", "swap_horiz", _SEQUENCE, ("mermaid", "diagram", "uml"))
_mermaid(
    "gantt", "Gantt chart", "view_timeline", _GANTT, ("mermaid", "diagram", "schedule", "timeline")
)


@command(
    "image",
    "Image",
    group="Media",
    icon="image",
    subtitle="Upload from your computer",
    hint="![]()",
    aliases=("picture", "photo", "img", "upload"),
)
def image(ctx: CommandContext) -> Action:
    return OpenPicker("image", "image")


@command(
    "table",
    "Table",
    group="Media",
    icon="table_chart",
    subtitle="3 × 3",
    hint="| |",
    aliases=("grid", "spreadsheet"),
)
def table(ctx: CommandContext) -> Action:
    """A 3 × 3 table (header + two rows), already tidy; the cursor goes into the first body cell."""
    blank = ["", "", ""]
    tidy = format_table(
        Table(["Column 1", "Column 2", "Column 3"], ["", "", ""], [blank, list(blank)])
    )
    return replace(block(ctx, tidy + "\n"), focus_cell=(1, 0))


LINKS = "Links"


@command(
    "link",
    "Link to note",
    group=LINKS,
    icon="link",
    hint="[[ ]]",
    aliases=("wikilink", "note", "reference"),
)
def link_to_note(ctx: CommandContext) -> Action:
    return OpenPicker("note", "link")


@command(
    "embed",
    "Embed note",
    group=LINKS,
    icon="note_add",
    hint="![[ ]]",
    aliases=("transclude", "include"),
)
def embed_note(ctx: CommandContext) -> Action:
    return OpenPicker("note", "embed")


INSERT = "Insert"


def _now() -> datetime:
    return datetime.now()


@command(
    "date",
    "Date",
    group=INSERT,
    icon="event",
    subtitle="Today",
    hint="YYYY-MM-DD",
    aliases=("today",),
)
def date_today(ctx: CommandContext) -> Action:
    return Insert(_now().strftime(DATE_FORMAT))


@command(
    "time",
    "Time",
    group=INSERT,
    icon="schedule",
    subtitle="Now",
    hint="HH:MM",
    aliases=("now", "clock"),
)
def time_now(ctx: CommandContext) -> Action:
    return Insert(_now().strftime(TIME_FORMAT))


def _has_templates(ctx: CommandContext) -> bool:
    folder = str(ctx.config.get("vault.templates_folder", "")) if ctx.config else ""
    return bool(folder.strip().strip("/")) and ctx.vault is not None and ctx.vault.exists(folder)


@command(
    "template",
    "Template",
    group=INSERT,
    icon="description",
    subtitle="From your templates folder",
    aliases=("snippet", "boilerplate"),
    when=_has_templates,
)
def template(ctx: CommandContext) -> Action:
    return OpenPicker("template", "template")


# ---- AI (streamed into the note; see EditorPane._run_stream) ----------------------------------

AI = "AI"
_has_selection = lambda ctx: bool(ctx.selection)  # noqa: E731


@command(
    "ai-summarize",
    "Summarize",
    group=AI,
    icon="summarize",
    subtitle="The selection, or the whole note",
    badge="AI",
    aliases=("summary", "tldr", "shorten"),
)
def ai_summarize(ctx: CommandContext) -> Action:
    return StreamInsert(
        "Summarize the text below concisely: a short paragraph, or a few bullet points if it "
        "has several parts. Keep the language of the text.",
        source="auto",
    )


@command(
    "ai-continue",
    "Continue writing",
    group=AI,
    icon="edit_note",
    subtitle="From where the caret is",
    badge="AI",
    aliases=("continue", "write more", "extend", "autocomplete"),
)
def ai_continue(ctx: CommandContext) -> Action:
    return StreamInsert(
        "Continue writing from exactly where the text below ends. Match its language, tone and "
        "markdown formatting. Write only the continuation.",
        source="before",
    )


@command(
    "ai-explain",
    "Explain selection",
    group=AI,
    icon="psychology",
    subtitle="Select text, then press Ctrl+J",
    badge="AI",
    aliases=("explain", "what does this mean"),
    when=_has_selection,
)
def ai_explain(ctx: CommandContext) -> Action:
    return StreamInsert(
        "Explain the text below clearly and briefly, for someone who knows the subject less well.",
        source="selection",
        lead="\n\n",
    )


@command(
    "ai-fix",
    "Fix grammar",
    group=AI,
    icon="spellcheck",
    subtitle="Replaces the selection",
    badge="AI",
    aliases=("grammar", "proofread", "spelling", "correct"),
    when=_has_selection,
)
def ai_fix(ctx: CommandContext) -> Action:
    return StreamInsert(
        "Fix the grammar, spelling and punctuation of the text below. Keep its meaning, tone, "
        "language and markdown formatting. Write only the corrected text.",
        source="selection",
        replace_selection=True,
    )


@command(
    "ai-ask",
    "Ask…",
    group=AI,
    icon="question_answer",
    subtitle="Ask the AI about this note",
    badge="AI",
    aliases=("question", "ask ai", "prompt", "write"),
)
def ai_ask(ctx: CommandContext) -> Action:
    return StreamInsert("", source="auto", ask=True)
