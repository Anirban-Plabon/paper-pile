"""The options box (PLAN §4.28, ``docs/AI_EDITS.md`` §8): the AI's message offering options for
a command run without words (or clearer versions of a messy request) — a tick box per option, a
last "Your own: …" field and **Apply N**. Length, tone and language are pick-one groups. The
same component in the Ask box's mini chat and the chat pane; what the options are comes from
core (``core/ai/options.py``), what Apply does is the caller's ``on_apply``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from nicegui import ui

from paper_pile.core.ai.options import SINGLE, Option, options_groups, options_instruction, tick
from paper_pile.gui.icons import line_icon

OWN_PLACEHOLDER = "Your own…"


class OptionsBox:
    """Built in the current slot. ``on_apply(instruction, groups)`` gets the ticked options and
    the own words as one instruction, and the ticked options' groups; after it the box is spent
    (greyed, no more clicks)."""

    def __init__(
        self,
        options: Sequence[Option],
        on_apply: Callable[[str, tuple[str, ...]], None],
        *,
        title: str = "",
    ) -> None:
        self._options = list(options)
        self._on_apply = on_apply
        self._ticked: list[Option] = []
        self._rows: dict[Option, ui.row] = {}
        self._spent = False
        with ui.column().classes("pp-optbox") as self.root:
            groups = {o.group for o in self._options}
            one = len(groups) == 1 and groups <= SINGLE  # all one pick-one group (tones…)
            ui.label(title or ("Pick one:" if one else "Pick one or more:")).classes(
                "pp-optbox-title"
            )
            for option in self._options:
                with ui.row().classes("pp-opt items-center no-wrap") as row:
                    with ui.element("span").classes("pp-opt-tick"):
                        line_icon("check", "s")
                    ui.label(option.label).classes("pp-opt-text")
                row.on("click", lambda _e, o=option: self._toggle(o))
                self._rows[option] = row
            with ui.row().classes("pp-opt pp-opt-own items-center no-wrap"):
                self._own = (
                    ui.input(placeholder=OWN_PLACEHOLDER)
                    .props("borderless dense")
                    .classes("pp-opt-own-input")
                )
                self._own.on_value_change(lambda _e: self._update())
                self._own.on("keydown.enter", lambda _e: self._apply())
            with ui.row().classes("pp-optbox-foot items-center no-wrap"):
                self._hint = ui.label("").classes("pp-muted pp-optbox-hint")
                self._button = ui.button("Apply", on_click=self._apply, color=None)
                self._button.props("flat no-caps dense").classes("pp-optbox-apply")
        self._update()

    def _toggle(self, option: Option) -> None:
        if self._spent:
            return
        before = set(self._ticked)
        self._ticked = tick(self._ticked, option)
        for o, row in self._rows.items():
            on = o in self._ticked
            row.classes(add="pp-opt-on" if on else "", remove="" if on else "pp-opt-on")
        dropped = before - set(self._ticked) - {option}
        single = option.group in SINGLE and (dropped or option in self._ticked)
        grouped = sum(o.group == option.group for o in self._options) > 1
        self._hint.set_text(f"Only one {option.group}" if single and grouped else "")
        self._update()

    def _update(self) -> None:
        count = len(self._ticked) + (1 if (self._own.value or "").strip() else 0)
        self._button.set_text(f"Apply {count}" if count else "Apply")
        self._button.set_enabled(count > 0 and not self._spent)
        self._button.classes(
            add="pp-optbox-ready" if count else "", remove="" if count else "pp-optbox-ready"
        )

    def _apply(self) -> None:
        ordered = [o for o in self._options if o in self._ticked]  # in the shown order
        instruction = options_instruction(ordered, self._own.value or "")
        if self._spent or not instruction:
            return
        self._spent = True
        self.root.classes(add="pp-optbox-spent")
        self._own.disable()
        self._update()
        self._on_apply(instruction, options_groups(ordered))
