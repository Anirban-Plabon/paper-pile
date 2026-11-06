"""From understood steps to a plan the agent can run (PLAN_vault_agent §3.3–3.4, §5.4; P30.14
/ P30.15): each step's target resolved to notes (or marked for a search, inside its scope),
notes taken from the last answer or from an earlier step, and what needs the user — an open
choice the model saw, or a name that fits several notes or folders — turned into one
question with options. Names that match nothing become notices, never guesses. No UI
imports, no model calls.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from paper_pile.core.ai.vault.results import ResultSet
from paper_pile.core.ai.vault.scope import ScopeResolver
from paper_pile.core.ai.vault.understand import Step, VaultRequest

MAX_CHOICES = 4


@dataclass(frozen=True, slots=True)
class Choice:
    """One question for the user. ``values[i]`` is what picking ``options[i]`` means: a note
    or folder path for a name (``kind`` "note" / "folder"), the option text for a model
    question (``kind`` "open")."""

    question: str
    options: tuple[str, ...]
    values: tuple[str, ...]
    kind: str  # "open" | "note" | "folder"
    step: int = -1  # the step the name belongs to (-1: the whole request)
    name: str = ""  # the name as the user wrote it


@dataclass(slots=True)
class PlannedStep:
    step: Step
    paths: list[str] | None = None  # the notes it works on; None: all readable notes
    search: bool = False  # search ``step.terms`` (inside ``paths`` when given)
    after: int = -1  # works on what step ``after`` found (resolved when that step ran)
    missing: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Plan:
    steps: list[PlannedStep]
    choice: Choice | None = None
    notices: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.choice is None


def _short(path: str) -> str:
    return path[:-3] if path.endswith(".md") else path


def _name_choice(index: int, name: str, candidates: Sequence[str], folder: bool) -> Choice:
    shown = list(candidates)[:MAX_CHOICES]
    kind = "folder" if folder else "note"
    question = f"Which {kind} do you mean by “{name}”?"
    return Choice(question, tuple(_short(c) for c in shown), tuple(shown), kind, index, name)


def _plan_step(
    index: int, step: Step, resolver: ScopeResolver, last: ResultSet | None, plan: Plan
) -> PlannedStep:
    out = PlannedStep(step, search=bool(step.terms))
    if step.depends_on >= 0:
        out.after = step.depends_on
        out.search = False  # it works on the earlier step's notes, not a new search
        return out
    readable = {r.path for r in resolver.readable()}
    if step.from_result and last is not None and len(last):
        picks: object = (
            "all" if step.from_result == "all" else [int(n) for n in step.from_result.split(",")]
        )
        out.paths = [i.path for i in last.pick(picks) if i.path in readable]
        out.search = False
        return out
    if step.scope.empty:
        return out  # the whole vault (searched when there are terms)
    res = resolver.resolve(step.scope)
    out.paths = res.paths
    out.missing = res.missing
    if res.missing:
        plan.notices.append("Not found: " + ", ".join(res.missing))
    if res.ambiguous and plan.choice is None:
        name, candidates = next(iter(res.ambiguous.items()))
        is_folder = name in step.scope.folders
        plan.choice = _name_choice(index, name, candidates, is_folder)
    if step.scope.notes and not step.terms:
        out.search = False  # named notes are read, not searched
    return out


_WORDS = re.compile(r"\w+", re.UNICODE)
STEM = 5  # letters two words must share at the start to count as the same word


def _stems(text: str) -> set[str]:
    return {w.casefold()[:STEM] for w in _WORDS.findall(text) if len(w) >= 3}


def mentioned(name: str, message: str) -> bool:
    """Does ``message`` mention the folder / tag ``name`` — one of its words (≥ 3 letters),
    compared by their first letters so "client" finds "Clients"?"""
    return bool(_stems(name.replace("/", " ")) & _stems(message))


def unguessed(step: Step, message: str, forced: Sequence[str] = ()) -> Step:
    """``step`` without the folders and tags the message never mentions, when the step
    searches for a topic: those are the model's guess where the topic is kept, and a guess
    must not hide the notes the user wants (gemma4 put "social business" in Marketing). A
    step with no terms keeps them — they are its only target ("my daily notes" → Journal).
    ``forced``: folders the message points at with ``@`` (always kept)."""
    if not step.terms or not message:
        return step
    keep_folders = tuple(
        f for f in step.scope.folders if mentioned(f, message) or f.strip("/") in forced
    )
    keep_tags = tuple(t for t in step.scope.tags if mentioned(t, message))
    if keep_folders == step.scope.folders and keep_tags == step.scope.tags:
        return step
    return replace(step, scope=replace(step.scope, folders=keep_folders, tags=keep_tags))


def make_plan(
    request: VaultRequest,
    resolver: ScopeResolver,
    last: ResultSet | None,
    message: str = "",
    forced: Sequence[str] = (),
) -> Plan:
    """The plan for ``request`` (the user's ``message``). The model's own open question
    comes first; else the first ambiguous name. Missing names are notices (the step then has
    fewer notes, maybe none). Guessed folders / tags of topic searches are dropped
    (:func:`unguessed`)."""
    plan = Plan(steps=[])
    for i, step in enumerate(request.steps):
        step = unguessed(step, message, [f.strip("/") for f in forced])
        plan.steps.append(_plan_step(i, step, resolver, last, plan))
    if request.question:
        opts = request.options[:MAX_CHOICES]
        plan.choice = Choice(request.question, opts, opts, "open")
    return plan


def choose(plan: Plan, value: str, resolver: ScopeResolver) -> Plan:
    """The user picked ``value`` for ``plan.choice``: a name choice narrows that step's name
    to the picked note / folder and the step is resolved again; an open choice is the
    caller's to fold into the request (it is cleared here). Other names left ambiguous ask
    next."""
    choice = plan.choice
    if choice is None:
        return plan
    out = Plan(steps=list(plan.steps), notices=list(plan.notices))
    if choice.kind == "open" or not 0 <= choice.step < len(plan.steps):
        return out
    planned = plan.steps[choice.step]
    scope = planned.step.scope
    if choice.kind == "folder":
        scope = replace(
            scope, folders=tuple(value if f == choice.name else f for f in scope.folders)
        )
    else:

        def swap(names: tuple[str, ...]) -> tuple[str, ...]:
            return tuple(value if n == choice.name else n for n in names)

        scope = replace(
            scope,
            notes=swap(scope.notes),
            linked_from=swap(scope.linked_from),
            links_to=swap(scope.links_to),
        )
    step = replace(planned.step, scope=scope)
    out.steps[choice.step] = _plan_step(choice.step, step, resolver, None, out)
    return out
