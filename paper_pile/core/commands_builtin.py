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
from paper_pile.core.pagebreak import PAGE_BREAK
from paper_pile.core.settings import feature_on
from paper_pile.core.spacing import spaced_block
from paper_pile.core.tables import Table, format_table
from paper_pile.core.templates import DATE_FORMAT, TIME_FORMAT

BASIC = "Basic blocks"

_BLOCK_LINES = {"bullet", "numbered", "todo", "quote"}
_HEADINGS = {"h1", "h2", "h3", "h4"}

# (id, title, icon, hint, line prefix, aliases)
_LINE_BLOCKS = [
    ("text", "Text", "type", "", "", ("paragraph", "plain")),
    ("h1", "Heading 1", "heading-1", "#", "# ", ("heading", "title", "header")),
    ("h2", "Heading 2", "heading-2", "##", "## ", ("heading", "subtitle", "header")),
    ("h3", "Heading 3", "heading-3", "###", "### ", ("heading", "header")),
    ("h4", "Heading 4", "heading-4", "####", "#### ", ("heading", "header")),
    ("bullet", "Bulleted list", "list", "-", "- ", ("ul", "list", "unordered")),
    ("numbered", "Numbered list", "list-ordered", "1.", "1. ", ("ol", "list", "ordered")),
    ("todo", "To-do list", "square-check", "[ ]", "- [ ] ", ("checkbox", "task", "checklist")),
    ("quote", "Quote", "quote", ">", "> ", ("blockquote", "cite")),
]


def _line_block(
    cid: str, title: str, icon: str, hint: str, prefix: str, aliases: tuple[str, ...]
) -> None:
    @command(cid, title, group=BASIC, icon=icon, hint=hint, aliases=aliases)
    def run(ctx: CommandContext) -> Action:
        # lists and quotes always get an empty line after them, so they end and can be left;
        # with "Blank lines around blocks" headings, lists and quotes get one above and below
        spaced = spacing_on(ctx) and cid in _BLOCK_LINES | _HEADINGS
        return ReplaceLinePrefix(
            prefix, blank_after=cid in _BLOCK_LINES or spaced, blank_before=spaced
        )


for _spec in _LINE_BLOCKS:
    _line_block(*_spec)


@command(
    "divider",
    "Divider",
    group=BASIC,
    icon="minus",
    hint="---",
    aliases=("hr", "rule", "line", "separator"),
)
def divider(ctx: CommandContext) -> Action:
    """A horizontal rule, spaced like every other block when "Blank lines around blocks" is on.
    Directly under a text line ``---`` would make that line a heading, so even with the setting
    off a blank line goes first unless there already is one."""
    if spacing_on(ctx):
        return block(ctx, "---", len("---\n"))  # the caret goes below the rule
    line_start = ctx.text.rfind("\n", 0, ctx.cursor) + 1
    previous = ctx.text[: line_start - 1].rsplit("\n", 1)[-1] if line_start else ""
    return Insert("\n---\n" if previous.strip() else "---\n")


@command(
    "page-break",
    "Page break",
    group=BASIC,
    icon="scissors-line-dashed",
    aliases=("pagebreak", "new page", "print", "pdf"),
)
def page_break(ctx: CommandContext) -> Action:
    """A manual page break (PLAN §4.17). It only counts with an empty line above and below,
    so both are always added (whatever "Blank lines around blocks" says), and the caret goes
    one line further down: typing right under the break would turn it back into text."""
    end = ctx.end if ctx.end is not None else ctx.cursor
    text, at = spaced_block(ctx.text, ctx.cursor, end, PAGE_BREAK, blank_lines=True)
    insert = text[:at] + PAGE_BREAK + "\n\n"
    return Insert(insert, len(insert))


# ---- blocks that need their own lines ---------------------------------------------------------


def spacing_on(ctx: CommandContext) -> bool:
    """Settings → Editor → Advanced → "Blank lines around blocks" (on by default)."""
    return ctx.config is None or bool(ctx.config.get("editor.block_spacing", True))


def block(ctx: CommandContext, body: str, caret: int | None = None) -> Insert:
    """Insert a multi-line ``body`` as a block on lines of its own, with an empty line above and
    below when the setting is on (``core/spacing.py``). ``caret`` is an offset into ``body``."""
    end = ctx.end if ctx.end is not None else ctx.cursor
    text, at = spaced_block(ctx.text, ctx.cursor, end, body, blank_lines=spacing_on(ctx))
    return Insert(text, min(len(text), at + (len(body) if caret is None else caret)))


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
    icon="sigma",
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
_KANBAN = (  # Mermaid's kanban diagram: a column per line, its cards indented under it
    "kanban\n    todo[To do]\n        t1[First card]\n        t2[Second card]\n"
    "    doing[Doing]\n        t3[Third card]\n    done[Done]\n        t4[Fourth card]\n"
)


def _mermaid(cid: str, title: str, icon: str, source: str, aliases: tuple[str, ...]) -> None:
    @command(cid, title, group=DIAGRAMS, icon=icon, hint="mermaid", aliases=aliases)
    def run(ctx: CommandContext) -> Action:
        return block(ctx, f"```mermaid\n{source}```\n")


_mermaid("flowchart", "Flowchart", "workflow", _FLOWCHART, ("mermaid", "diagram", "graph"))
_mermaid(
    "sequence", "Sequence diagram", "arrow-left-right", _SEQUENCE, ("mermaid", "diagram", "uml")
)
_mermaid(
    "gantt", "Gantt chart", "chart-gantt", _GANTT, ("mermaid", "diagram", "schedule", "timeline")
)
_mermaid("kanban", "Kanban board", "square-kanban", _KANBAN, ("mermaid", "board", "cards", "todo"))


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
    icon="table",
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
    icon="file-plus",
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
    icon="calendar",
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
    icon="clock",
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
    icon="file-text",
    subtitle="From your templates folder",
    aliases=("snippet", "boilerplate"),
    when=_has_templates,
)
def template(ctx: CommandContext) -> Action:
    return OpenPicker("template", "template")


# ---- AI (streamed into the note; see EditorPane._run_stream) ----------------------------------

AI = "AI"


def _ai_on(ctx: CommandContext) -> bool:
    """AI commands exist only while the AI feature is on (Settings → General → Features)."""
    return ctx.config is None or feature_on(ctx.config.values, "features.ai")


def _ai_on_selection(ctx: CommandContext) -> bool:
    return _ai_on(ctx) and bool(ctx.selection)


@command(
    "ai-summarize",
    "Summarize",
    group=AI,
    icon="scroll-text",
    subtitle="The selection, or the whole note",
    badge="AI",
    aliases=("summary", "tldr", "shorten"),
    when=_ai_on,
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
    icon="pencil-line",
    subtitle="From where the caret is",
    badge="AI",
    aliases=("continue", "write more", "extend", "autocomplete"),
    when=_ai_on,
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
    icon="brain",
    subtitle="Select text, then press Ctrl+J",
    badge="AI",
    aliases=("explain", "what does this mean"),
    when=_ai_on_selection,
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
    icon="spell-check",
    subtitle="Replaces the selection",
    badge="AI",
    aliases=("grammar", "proofread", "spelling", "correct"),
    when=_ai_on_selection,
)
def ai_fix(ctx: CommandContext) -> Action:
    return StreamInsert(
        "Fix the grammar, spelling and punctuation of the text below. Keep its meaning, tone, "
        "language and markdown formatting. Write only the corrected text.",
        source="selection",
        replace_selection=True,
    )


def edit_selection(instruction: str) -> StreamInsert:
    """The selection bar's Edit: change the selected text as the user asked (shown as a diff)."""
    return StreamInsert(
        f"Change the text below as asked: {instruction.strip()}. Keep its language and markdown "
        "formatting unless asked otherwise. Write only the new text.",
        source="selection",
        replace_selection=True,
    )


@command(
    "ai-ask",
    "Ask…",
    group=AI,
    icon="sparkles",
    subtitle="Ask the AI about this note",
    badge="AI",
    aliases=("question", "ask ai", "prompt", "write"),
    when=_ai_on,
)
def ai_ask(ctx: CommandContext) -> Action:
    return StreamInsert("", source="auto", ask=True)
