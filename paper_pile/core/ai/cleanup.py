"""The text to put into a note from a model's answer (PLAN §4.29, ``docs/AI_EDITS.md`` §6.2):
the same rules for every AI change, so no "Sure! Here is…" or "Let me know…" ever lands in a
note.

``clean_reply`` cleans a finished answer (a change, before its diff). ``StreamCleaner`` cleans an
answer while it streams into the note, character by character (user 2026-11-19: it used to come
paragraph by paragraph): it holds back the first line until it knows it is not a preamble, the
start of each paragraph until it cannot be a closing remark ("Let me know…", held whole and
dropped when it is the last), a line that may be a heading or a fence until it is complete, and
trailing spaces / blank lines until more text follows — so none of them is ever written.
Headings in an answer are kept below the section it is written into. No UI imports.
"""

import re

from paper_pile.core.parser import headings

_THINK = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)
_PREAMBLE = re.compile(
    r"(?:sure|okay|ok|certainly|of course|absolutely|here(?:'s| is| are)|below is|this is)\b"
    r"[^\n]{0,120}:\s*$",
    re.IGNORECASE,
)
_LABEL = re.compile(
    r"(?:\[?B\d+(?:[–-]B\d+)?\]?|block b\d+|translation|translated text|rewritten text|"
    r"revised text|new text|corrected text|summary|outline|explanation|answer|output|result)"
    r"\s*:?\s*$",
    re.IGNORECASE,
)
_CLOSING = re.compile(
    r"(?:let me know|i hope|hope this|feel free|i(?:'ve| have) (?:fixed|corrected|changed|made|"
    r"kept|rewritten)|(?:the )?changes? (?:made|include)|note:|\(note:)",
    re.IGNORECASE,
)
_FENCE = re.compile(r"(`{3,}|~{3,})[\w-]*\n(.*?)\n?\1\s*", re.DOTALL)
_FENCE_OPEN = re.compile(r"^(`{3,}|~{3,})[\w-]*\s*$")
_FRONT = re.compile(r"\A---\n.*?\n---\s*(?:\n|\Z)", re.DOTALL)
_WRAP = re.compile(r"^\s*(?:<<<|>>>)\s*$", re.MULTILINE)
_HEADING = re.compile(r"^(#{1,6})([ \t]+)(.*)$")
HEAD_LIMIT = 200  # characters held back at most while deciding about the first line
CLOSE_DECIDE = 24  # a paragraph's first characters held back: by then a closing remark shows


_NOISE_START = re.compile(
    r"(?:sure|okay|ok|certainly|of course|absolutely|here|below is|this is|<<<|>>>)\b",
    re.IGNORECASE,
)
MATH_HOLD = 1500  # characters an unfinished formula is held back at most (a stray "$")
LABEL_MAX = 32  # longer than this, a first line is no label ("Translation:", "[B3]:")


def _may_be_noise(start: str) -> bool:
    """The first line so far (not complete) may still turn out a preamble, label or wrapper."""
    s = start.strip().lower()
    if len(s) <= LABEL_MAX or s[:1] in "`~#<>[":
        return True
    return bool(_NOISE_START.match(s))


def open_math_at(line: str) -> int | None:
    """Where an inline formula that is not closed yet starts in ``line`` (a ``$`` with no
    closing ``$``; ``\\$``, ``$$`` and code spans aside), else None. Streaming holds it back
    until it is complete, so it never shows as raw TeX that then jumps into a formula (user
    2026-11-19)."""
    opened: int | None = None
    i, code = 0, False
    while i < len(line):
        c = line[i]
        if c == "\\":
            i += 2
            continue
        if c == "`":
            code = not code
        elif c == "$" and not code:
            if line.startswith("$$", i):
                i += 2
                continue
            opened = i if opened is None else None
        i += 1
    return opened


def open_display_math(text: str) -> int | None:
    """Where a ``$$`` display formula that is not closed yet starts in ``text``, else None."""
    at, start, inside = 0, None, False
    while (found := text.find("$$", at)) >= 0:
        if found and text[found - 1] == "\\":
            at = found + 2
            continue
        inside, start = not inside, found
        at = found + 2
    return start if inside else None


def streaming_view(text: str) -> str:
    """A streaming answer as far as it can be drawn: an unfinished formula at its end is left
    out until it is complete (the chat redraws the answer as it grows)."""
    display = open_display_math(text)
    if display is not None and len(text) - display <= MATH_HOLD:
        return text[:display]
    start = text.rfind("\n") + 1
    inline = open_math_at(text[start:])
    if inline is not None and len(text) - start - inline <= MATH_HOLD:
        return text[: start + inline]
    return text


def _first_line_is_noise(line: str) -> bool:
    s = line.strip()
    return bool(_PREAMBLE.fullmatch(s) or _LABEL.fullmatch(s) or _WRAP.fullmatch(s))


def clean_reply(text: str, original: str = "") -> str:
    """The text in a model's answer (see the module docstring). A fence around everything is
    kept when ``original`` was one; properties at the start are kept when ``original`` began
    with them."""
    out = _THINK.sub("", text)
    if re.match(r"\s*<think>", out, re.IGNORECASE):
        return ""  # reasoning that never ended: no answer
    out = _WRAP.sub("", out).strip()
    first, _, rest = out.partition("\n")
    if rest.strip() and _first_line_is_noise(first):
        out = rest.strip()
    head, sep, last = out.rpartition("\n\n")
    if sep and head.strip() and _CLOSING.match(last.strip()):
        out = head.strip()
    fenced = _FENCE.fullmatch(out)
    if fenced and not _FENCE.fullmatch(original.strip()):
        out = fenced.group(2)
    if not original.lstrip().startswith("---"):
        out = _FRONT.sub("", out, count=1).lstrip("\n")
    out = "\n".join(line.rstrip() for line in out.split("\n")).strip("\n")
    return out if original.strip() else _space_headings(out)


def _space_headings(text: str) -> str:
    """New text: a blank line after each heading that runs straight into text (not in code),
    as the note's own sections are written."""
    lines, out, code = text.split("\n"), [], False
    for i, line in enumerate(lines):
        if _FENCE_OPEN.match(line.strip()):
            code = not code
        out.append(line)
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if not code and _HEADING.match(line.strip()) and nxt.strip():
            out.append("")
    return "\n".join(out)


def demote(line: str, floor: int) -> str:
    """A heading line at level ``floor`` or above, moved to ``floor + 1`` (at most 6)."""
    m = _HEADING.match(line)
    if m is None or floor < 1 or len(m.group(1)) > floor:
        return line
    return "#" * min(6, floor + 1) + m.group(2) + m.group(3)


class StreamCleaner:
    """Cleans a streamed answer piece by piece (see the module docstring).

    ``heading_floor``: the level of the section the answer is written into — its headings are
    kept below it; ``title``: a first heading repeating it is dropped; ``avoid_bullet``: the
    list just above the answer uses this marker — the answer's own list items use another, so
    the two stay two lists."""

    def __init__(self, heading_floor: int = 0, title: str = "", avoid_bullet: str = "") -> None:
        self.floor = heading_floor
        self.title = title.strip().lower()
        self.avoid = avoid_bullet
        self._buf = ""
        self._head_done = False
        self._thinking = False
        self._outer_fence = ""  # the fence the model wrapped everything in
        self._in_code = False
        self._sent_any = False
        self._wrote = False  # something was written (newlines before more text are kept)
        self._in_para = False  # the current paragraph's start is written: no closing remark
        self._mid_line = False  # the last write ended inside a line
        self._in_display = False  # inside a $$ formula already written (held until complete)

    def feed(self, piece: str) -> str:
        """The part of the answer that can be written now."""
        self._buf += piece
        if not self._strip_thinking():
            return ""
        if not self._head_done and not self._decide_head(final=False):
            return ""
        return self._drain(final=False)

    def finish(self) -> str:
        """The rest of the answer, once it is complete."""
        if not self._strip_thinking(final=True):
            return ""
        if not self._head_done:
            self._decide_head(final=True)
        self._buf = self._buf.rstrip()
        if self._outer_fence:
            self._buf = re.sub(rf"\n?{re.escape(self._outer_fence)}\s*\Z", "", self._buf)
        out = self._drain(final=True)
        self._buf = ""
        return out

    def _drain(self, *, final: bool) -> str:
        """Writes what is safe of the buffer, line by line; a line's start is decided once."""
        out: list[str] = []
        while self._buf:
            if self._mid_line:  # the rest of a line already begun: plain text
                end = self._buf.find("\n")
                part = self._buf if end < 0 else self._buf[:end]
                if end < 0 and not final:
                    part = self._ready_part(part)  # an open formula and trailing spaces wait
                elif not final or end >= 0:
                    part = part.rstrip(" \t")  # trailing spaces: dropped at the line end
                out.append(part)
                self._buf = self._buf[len(part) :]
                if end < 0:
                    break
                self._mid_line = False
                continue
            text = self._buf.lstrip("\n")
            newlines = len(self._buf) - len(text)
            if not text:
                break  # only line breaks: they wait for more text (an answer never ends in them)
            if newlines >= 2 and not self._in_code:
                self._in_para = False  # a blank line: a new paragraph
            if not self._in_para and not self._in_code:
                para = text.split("\n\n", 1)[0].strip()
                last = "\n\n" not in text
                if last and _CLOSING.match(para):  # a closing remark: kept back, dropped at the end
                    if final:
                        self._buf = ""
                    break
                if last and not final and len(para) < CLOSE_DECIDE:
                    break  # too short yet to tell
            end = text.find("\n")
            line = text if end < 0 else text[:end]
            if (
                not final
                and not self._in_code
                and not self._in_display
                and line.lstrip().startswith("$$")
            ):
                closed = open_display_math(text) is None
                if not closed and len(text) <= MATH_HOLD:
                    break  # a display formula is written once it is complete
            if end < 0 and not final:
                head = line.lstrip()[:1]
                if head in ("`", "~") or (head == "#" and not self._in_code) or len(line) < 2:
                    break  # a fence / heading / list marker is decided on the whole line
            gap = ""
            if self._wrote:
                gap = "\n" * newlines if self._in_code else ("\n\n" if newlines >= 2 else "\n")
            if end < 0:  # the start of a line still being written
                written = line if final else self._ready_part(line)
                done = self._emit(written)
                self._buf = text[len(written) :]
                self._mid_line = True
            else:
                done = self._emit(line.rstrip(" \t"))
                self._buf = text[end:]
                if not self._in_code and open_display_math(line) is not None:
                    self._in_display = not self._in_display  # an odd number of $$ on the line
            if done or end < 0:
                out.append(gap + done)
                self._wrote = True
                self._in_para = self._in_para or (not self._in_code and bool(done.strip()))
        return "".join(out)

    def _strip_thinking(self, final: bool = False) -> bool:
        """Drops reasoning; False while still inside it."""
        if not self._sent_any and not self._head_done:
            low = self._buf.lstrip().lower()
            if low.startswith("<think>"):
                self._thinking = True
            elif "<think>".startswith(low) and low and not final:
                return False  # maybe the start of "<think>"
        if self._thinking:
            end = self._buf.lower().find("</think>")
            if end < 0:
                if final:
                    self._buf = ""
                return False
            self._buf = self._buf[end + len("</think>") :].lstrip()
            self._thinking = False
        return True

    def _decide_head(self, *, final: bool) -> bool:
        """Drops a preamble / label line, an opening fence around everything and a heading that
        repeats the title, once the first line is complete; False while it is not."""
        while True:
            text = self._buf.lstrip("\n")
            line, nl, rest = text.partition("\n")
            if not nl and not final and len(text) < HEAD_LIMIT and _may_be_noise(line):
                return False
            if _first_line_is_noise(line) and (rest.strip() or not final):
                self._buf = rest
                continue
            fence = _FENCE_OPEN.match(line.strip())
            if fence and not self._outer_fence and nl:
                self._outer_fence = fence.group(1)
                self._buf = rest
                continue
            m = _HEADING.match(line.strip())
            if m and self.title and m.group(3).strip().lower() == self.title:
                self._buf = rest
                continue
            self._buf = text
            self._head_done = True
            return True

    def _ready_part(self, line: str) -> str:
        """What of a line still being written can go now: not an unfinished inline formula
        (unless it got too long to be one), not trailing spaces."""
        at = None if self._in_code else open_math_at(line)
        if at is not None and len(line) - at <= MATH_HOLD:
            line = line[:at]
        return line.rstrip(" \t")

    def _emit(self, text: str) -> str:
        out = []
        for line in text.split("\n"):
            if self._outer_fence and line.strip() == self._outer_fence and not self._in_code:
                self._outer_fence = ""  # the end of the fence around everything
                continue
            if _FENCE_OPEN.match(line.strip()):
                self._in_code = not self._in_code
            if not self._in_code and self.avoid and line.startswith(f"{self.avoid} "):
                line = ("*" if self.avoid == "-" else "-") + line[1:]
            out.append(line if self._in_code else demote(line, self.floor))
        done = "\n".join(out)
        if done.strip():
            self._sent_any = True
        return done


def heading_floor(note: str, at: int) -> int:
    """The level of the section offset ``at`` of ``note`` is in (0 before any heading): an
    answer written there keeps its headings below it."""
    line = note.count("\n", 0, at) + 1
    above = [h.level for h in headings(note) if h.line <= line]
    return above[-1] if above else 0
