"""What the AI may read (PLAN §4.26): per-vault grants in ai_access.json and the policy."""

import json
from pathlib import Path

import pytest

from paper_pile.core.ai.access import (
    AccessDeniedError,
    AccessPolicy,
    Grant,
    access_file,
    check_outside_path,
    grant_now,
    load_grant,
    parse_types,
    paths_in,
    revoke,
    save_grant,
    says_private,
)
from paper_pile.core.ai.context import EditorSnapshot
from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.commands import StreamInsert
from paper_pile.core.config import Config
from paper_pile.core.vault import Vault


@pytest.fixture
def cfg_dir(tmp_path: Path) -> Path:
    return tmp_path / "config"


def test_grant_is_for_the_exact_vault_only(tmp_path: Path, cfg_dir: Path) -> None:
    parent = tmp_path / "A"
    b = parent / "B"
    child = b / "C"
    other = tmp_path / "D"
    for d in (child, other):
        d.mkdir(parents=True)
    grant_now(b, cfg_dir)
    assert load_grant(b, cfg_dir) is not None
    assert load_grant(b / "." / "C" / "..", cfg_dir) is not None  # the same folder, resolved
    for vault in (parent, child, other):
        assert load_grant(vault, cfg_dir) is None
    data = json.loads(access_file(cfg_dir).read_text())
    assert list(data["vaults"]) == [str(b.resolve())]
    revoke(b, cfg_dir)
    assert load_grant(b, cfg_dir) is None


def test_moved_vault_asks_again(tmp_path: Path, cfg_dir: Path) -> None:
    old = tmp_path / "old"
    old.mkdir()
    grant_now(old, cfg_dir)
    new = old.rename(tmp_path / "new")
    assert load_grant(new, cfg_dir) is None


def test_damaged_file_and_records_mean_no_grant(tmp_path: Path, cfg_dir: Path) -> None:
    cfg_dir.mkdir()
    access_file(cfg_dir).write_text("{not json")
    assert load_grant(tmp_path, cfg_dir) is None
    key = str(tmp_path.resolve())
    access_file(cfg_dir).write_text(json.dumps({"vaults": {key: {"file_types": [".md"]}}}))
    assert load_grant(tmp_path, cfg_dir) is None  # no "granted" time
    record = {"granted": "2026-10-28T10:00", "file_types": "md", "exclude": [3, "a"]}
    access_file(cfg_dir).write_text(json.dumps({"vaults": {key: record}}))
    grant = load_grant(tmp_path, cfg_dir)
    assert grant is not None and grant.file_types == [] and grant.exclude == ["a"]


def test_policy_types_never_folders_and_exclusions(tmp_path: Path) -> None:
    grant = Grant("now", [".md"], exclude=["private", "*.secret.md", "journal/2024"])
    memory = tmp_path / "AI chats"
    policy = AccessPolicy(tmp_path, grant, memory)
    assert (
        policy.may_read("a.md") and policy.may_read("sub/b.md") and policy.may_read("privates.md")
    )
    for denied in (
        "a.txt",
        ".trash/a.md",
        ".paper-pile/x.md",
        "AI chats/c.md",
        "private/x.md",
        "private",
        "x.secret.md",
        "journal/2024/jan.md",
        "",
    ):
        assert not policy.may_read(denied), denied
    assert AccessPolicy(tmp_path, None).may_read("a.md") is False


def test_ai_false_in_properties() -> None:
    assert says_private("---\nai: false\ntags: [x]\n---\nbody")
    assert not says_private("---\nai: true\n---\nbody")
    assert not says_private("---\nai: no way: [\n---\nbody")  # broken YAML: not private
    assert not says_private("no front matter\nai: false")


def test_outside_paths(tmp_path: Path, cfg_dir: Path) -> None:
    vault = tmp_path / "vault"
    shared = tmp_path / "shared"
    (shared / ".git").mkdir(parents=True)
    vault.mkdir()
    (shared / "a.md").write_text("outside a")
    (shared / "b.py").write_text("print(1)")
    (shared / ".git" / "c.md").write_text("hidden")
    (tmp_path / "loose.md").write_text("not granted")
    one = tmp_path / "one.txt"
    one.write_text("single file")
    grant = Grant("now", [".md", ".txt"], [str(shared), str(one)])
    policy = AccessPolicy(vault, grant)
    assert policy.outside_files() == [(shared / "a.md").resolve(), one.resolve()]
    assert policy.read_outside(shared / "a.md") == "outside a"
    assert policy.read_outside(shared / "b.py") is None  # type not allowed
    assert policy.read_outside(tmp_path / "loose.md") is None
    assert policy.read_outside(shared / ".." / "loose.md") is None
    assert check_outside_path(str(shared), vault) == ""
    (vault / "sub").mkdir()
    assert check_outside_path(str(vault / "sub"), vault) == "That is inside this vault already."
    assert check_outside_path(str(vault), vault) == "That is inside this vault already."
    assert check_outside_path("relative/path", vault).startswith("Use a full path")
    assert check_outside_path(str(tmp_path / "nope"), vault) == "No such file or folder."


def test_parse_types() -> None:
    assert parse_types("md, .TXT *.py  py bad/") == [".md", ".txt", ".py"]


# ---- the engine enforces it ---------------------------------------------------------------


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    v = Vault(tmp_path / "v")
    v.root.mkdir()
    v.create_note("a.md", "alpha body")
    v.create_note("b.md", "beta body")
    v.create_note("secret.md", "---\nai: false\n---\nsecret body")
    v.create_folder("hidden")
    v.create_note("hidden/h.md", "hidden body")
    v.create_note("t.txt", "text body")
    return v


def make(vault: Vault, fake: FakeProvider, cfg_dir: Path) -> AiEngine:
    return AiEngine(vault, Config(vault=vault.root), provider_factory=lambda _c: fake,
                    access_dir=cfg_dir)  # fmt: skip


async def test_engine_refuses_without_a_grant(vault: Vault, cfg_dir: Path) -> None:
    fake = FakeProvider(delay=0)
    ai = make(vault, fake, cfg_dir)
    assert not ai.has_access()
    out = ai.add_message("hi")
    with pytest.raises(AccessDeniedError):
        async for _ in ai.answer(ai.start_reply(), out, EditorSnapshot("a.md", "alpha body")):
            pass
    with pytest.raises(AccessDeniedError):
        await ai.command_messages(StreamInsert("Sum"), path="a.md", text="alpha body", caret=0)
    assert fake.calls == []  # nothing reached the model
    ai.allow()
    assert ai.has_access() and load_grant(vault.root, cfg_dir) is not None


async def test_engine_sends_only_what_the_policy_allows(vault: Vault, cfg_dir: Path) -> None:
    fake = FakeProvider(delay=0)
    save_grant(vault.root, Grant("now", [".md"], exclude=["hidden"]), cfg_dir)
    ai = make(vault, fake, cfg_dir)
    out = ai.add_message("see @b @secret @hidden/h @t")
    snap = EditorSnapshot(
        "secret.md",
        "---\nai: false\n---\nsecret body",
        selection="live selection",
        tabs=[("hidden/h.md", "hidden body"), ("b.md", "beta body")],
    )
    async for _ in ai.answer(ai.start_reply(), out, snap, include_tabs=True):
        pass
    sent = "\n".join(m.content for m in fake.calls[-1])
    assert "beta body" in sent
    for never in ("secret body", "live selection", "hidden body", "text body"):
        assert never not in sent, never
    chip = ai.selection("chosen on purpose", "secret.md")
    out = ai.add_message("and this", [chip])
    async for _ in ai.answer(ai.start_reply(), out, EditorSnapshot()):
        pass
    assert "chosen on purpose" in fake.calls[-1][-1].content  # an attached chip is sent
    with pytest.raises(AccessDeniedError):
        await ai.command_messages(
            StreamInsert("Sum"), path="secret.md", text="---\nai: false\n---\nx", caret=0
        )
    ai.revoke_access()
    assert not ai.has_access()


def test_paths_in_a_message(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    papers = tmp_path / "papers"
    (vault / "sub").mkdir(parents=True)
    papers.mkdir()
    one = tmp_path / "one.md"
    one.write_text("x")
    text = (
        f"read {papers}, and {one}. Also {vault / 'sub'} (in the vault), "
        f"{tmp_path / 'nope'} and http://x.org/a/b and {papers} again"
    )
    assert paths_in(text, vault) == [papers.resolve(), one.resolve()]


async def test_allow_a_folder_from_the_chat(vault: Vault, cfg_dir: Path, tmp_path: Path) -> None:
    papers = tmp_path / "papers"
    (papers / "deep").mkdir(parents=True)
    (papers / "p1.md").write_text("first paper")
    (papers / "deep" / "p2.md").write_text("second paper")
    (papers / "x.bin").write_bytes(b"\x00\x01")
    fake = FakeProvider(delay=0)
    ai = make(vault, fake, cfg_dir)
    question = f"summarize {papers}"
    assert ai.paths_to_ask(question) == [papers.resolve()]
    ai.allow_path(papers)  # no vault grant yet: nothing is recorded
    assert ai.paths_to_ask(question) == [papers.resolve()]
    ai.allow()
    ai.allow_path(papers)
    assert ai.paths_to_ask(question) == [] and ai.paths_to_ask(f"see {papers / 'deep'}") == []
    out = ai.add_message(question)
    async for _ in ai.answer(ai.start_reply(), out, EditorSnapshot()):
        pass
    sent = fake.calls[-1][-1].content
    assert "first paper" in sent and "second paper" in sent
    assert out.turn.attachment.count("[Outside file]") == 2
    grant = load_grant(vault.root, cfg_dir)
    assert grant is not None and grant.allow_paths == [str(papers.resolve())]
    other = make(Vault(tmp_path), FakeProvider(delay=0), cfg_dir)  # another vault: not granted
    assert not other.has_access()
