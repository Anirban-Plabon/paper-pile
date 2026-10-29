from pathlib import Path

from paper_pile.core.config import DEFAULTS, Config, deep_merge


def test_deep_merge_recurses_and_does_not_mutate() -> None:
    base = {"a": {"x": 1, "y": 2}, "b": 1}
    out = deep_merge(base, {"a": {"y": 3}, "c": 4})
    assert out == {"a": {"x": 1, "y": 3}, "b": 1, "c": 4}
    assert base == {"a": {"x": 1, "y": 2}, "b": 1}


def test_defaults_when_no_files(tmp_path: Path) -> None:
    cfg = Config(global_path=tmp_path / "g.toml")
    assert cfg.values == DEFAULTS
    assert cfg.get("ai.model") == "gemma4:12b"
    assert cfg.get("nope.missing", "fallback") == "fallback"


def test_merge_order_defaults_global_vault(tmp_path: Path) -> None:
    g = tmp_path / "g.toml"
    g.write_text('[editor]\nfont_size = 16\ntab_size = 2\n[appearance]\ntheme = "dark"\n')
    vault = tmp_path / "vault"
    (vault / ".paper-pile").mkdir(parents=True)
    (vault / ".paper-pile" / "vault.toml").write_text("[editor]\nfont_size = 20\n")
    cfg = Config(global_path=g, vault=vault)
    assert cfg.get("editor.font_size") == 20  # vault beats global
    assert cfg.get("editor.tab_size") == 2  # global beats default
    assert cfg.get("editor.line_height") == DEFAULTS["editor"]["line_height"]
    assert cfg.get("appearance.theme") == "dark"


def test_save_round_trip_writes_only_overrides(tmp_path: Path) -> None:
    g = tmp_path / "sub" / "g.toml"
    cfg = Config(global_path=g)
    cfg.set("editor.font_size", 18)
    cfg.set("paste.smart_paste", False)
    cfg.save()
    assert g.read_text().count("[") == 2  # only the two touched tables
    again = Config(global_path=g)
    assert again.get("editor.font_size") == 18
    assert again.get("paste.smart_paste") is False
    assert again.get("editor.tab_size") == DEFAULTS["editor"]["tab_size"]


def test_vault_scope_saved_separately(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    cfg = Config(global_path=tmp_path / "g.toml", vault=vault)
    cfg.set("ai.model", "other", scope="vault")
    cfg.save("vault")
    assert not (tmp_path / "g.toml").exists()
    assert Config(global_path=tmp_path / "g.toml", vault=vault).get("ai.model") == "other"
    assert Config(global_path=tmp_path / "g.toml").get("ai.model") == "gemma4:12b"


def test_vault_scope_without_vault_raises(tmp_path: Path) -> None:
    cfg = Config(global_path=tmp_path / "g.toml")
    try:
        cfg.set("a.b", 1, scope="vault")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_corrupt_file_ignored_and_backed_up_on_save(tmp_path: Path) -> None:
    g = tmp_path / "g.toml"
    g.write_text("this is = not [valid")
    cfg = Config(global_path=g)
    assert cfg.values == DEFAULTS
    cfg.set("editor.font_size", 12)
    cfg.save()
    assert (tmp_path / "g.toml.bak").read_text() == "this is = not [valid"
    assert Config(global_path=g).get("editor.font_size") == 12


def test_set_does_not_alter_defaults(tmp_path: Path) -> None:
    cfg = Config(global_path=tmp_path / "g.toml")
    cfg.set("editor.font_size", 99)
    assert DEFAULTS["editor"]["font_size"] == 14


def test_a_vault_cannot_set_the_ai_security_keys(tmp_path: Path) -> None:
    from paper_pile.core.config import GLOBAL_ONLY, scope_for

    vault = tmp_path / "v"
    (vault / ".paper-pile").mkdir(parents=True)
    (vault / ".paper-pile" / "vault.toml").write_text(
        '[ai]\nhost = "http://attacker:11434"\ninstructions_file = "/etc/passwd"\n'
        'chats_folder = "/tmp/x"\nprompts_file = "/tmp/p.md"\nedits = "auto"\nmodel = "m"\n'
    )
    cfg = Config(global_path=tmp_path / "g.toml", vault=vault)
    for key in GLOBAL_ONLY:
        assert cfg.get(key) == Config(global_path=tmp_path / "g.toml").get(key)
    assert cfg.get("ai.model") == "m"  # other keys still differ per vault
    assert scope_for("ai.host", "vault") == "global" and scope_for("ai.model", "vault") == "vault"
    try:
        cfg.set("ai.host", "http://x", scope="vault")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
