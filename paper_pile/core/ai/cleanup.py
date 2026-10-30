"""The text to put into a note from a model's answer (PLAN §4.29, ``docs/AI_EDITS.md`` §6.2):
the same rules for every AI change, so no "Sure! Here is…" or "Let me know…" ever lands in a
note.

``clean_reply`` cleans a finished answer (a change, before its diff). ``StreamCleaner`` cleans an
answer while it streams into the note: it holds back the first line until it knows it is not a
preamble, and always holds back the last paragraph until the next one starts, so a closing
remark or the end of a code fence around everything is never written in the first place.
Headings in an answer are kept below the section it is written into. No UI imports.
"""

import re

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
    return "\n".join(line.rstrip() for line in out.split("\n")).strip("\n")


def demote(line: str, floor: int) -> str:
    """A heading line at level ``floor`` or above, moved to ``floor + 1`` (at most 6)."""
    m = _HEADING.match(line)
    if m is None or floor < 1 or len(m.group(1)) > floor:
        return line
    return "#" * min(6, floor + 1) + m.group(2) + m.group(3)


class StreamCleaner:
    """Cleans a streamed answer piece by piece (see the module docstring).

    ``heading_floor``: the level of the section the answer is written into — its headings are
    kept below it; ``title``: a first heading repeating it is dropped."""

    def __init__(self, heading_floor: int = 0, title: str = "") -> None:
        self.floor = heading_floor
        self.title = title.strip().lower()
        self._buf = ""
        self._head_done = False
        self._thinking = False
        self._outer_fence = ""  # the fence the model wrapped everything in
        self._in_code = False
        self._sent_any = False
        self._gap = False  # something was written: the next paragraph starts after a gap

    def feed(self, piece: str) -> str:
        """The part of the answer that can be written now."""
        self._buf += piece
        if not self._strip_thinking():
            return ""
        if not self._head_done and not self._decide_head(final=False):
            return ""
        cut = self._buf.rfind("\n\n")
        if cut < 0:
            return ""
        ready, self._buf = self._buf[:cut], self._buf[cut + 2 :]
        return self._joined(self._emit(ready))

    def finish(self) -> str:
        """The rest of the answer, once it is complete."""
        if not self._strip_thinking(final=True):
            return ""
        if not self._head_done:
            self._decide_head(final=True)
        rest = self._buf.rstrip()
        self._buf = ""
        if self._outer_fence:
            rest = re.sub(rf"\n?{re.escape(self._outer_fence)}\s*\Z", "", rest)
        head, sep, last = rest.rpartition("\n\n")
        if _CLOSING.match(last.strip()):
            rest = head if sep else ""
        return self._joined(self._emit(rest).rstrip())

    def _joined(self, text: str) -> str:
        """``text`` after the blank line that separates it from what was written before (held
        back until now, so an answer never ends with empty lines)."""
        body = text.strip("\n")
        if not body:
            return ""
        out = ("\n\n" if self._gap else "") + body
        self._gap = True
        return out

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
            if not nl and not final and len(text) < HEAD_LIMIT:
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

    def _emit(self, text: str) -> str:
        out = []
        for line in text.split("\n"):
            if self._outer_fence and line.strip() == self._outer_fence and not self._in_code:
                self._outer_fence = ""  # the end of the fence around everything
                continue
            if _FENCE_OPEN.match(line.strip()):
                self._in_code = not self._in_code
            out.append(line if self._in_code else demote(line, self.floor))
        done = "\n".join(out)
        if done.strip():
            self._sent_any = True
        return done
