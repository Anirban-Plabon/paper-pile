"""Remove what paper-pile's requests left in the user's own Antigravity CLI data (TRACKER P28.8).

Before P28.8 the app ran ``agy`` with the user's real ``HOME``, so ``~/.gemini/antigravity-cli``
kept titles, summaries and prompt previews of the app's requests (built from notes), and a log
per run — model answers included. The app now runs agy in its own home and wipes it after each
session; this tool cleans what older versions left, once:

    uv run python tools/agy_forget_app.py            # dry run: what would go (reads only)
    uv run python tools/agy_forget_app.py --apply    # remove it (no agy may be running)

Removed: the conversations whose workspace is one of the app's (its agy folder, its QA runs,
its development test folders) — their rows in ``conversation_summaries.db`` (then vacuumed, so
the text is gone from the file), their entries in ``cache/conversation_metadata.json`` and
``cache/last_conversations.json``, their conversation / brain / annotation / presence files;
``jetbox_summaries_proto.pb`` (agy rebuilds it from the cleaned database at its next start);
log files of the app's workspaces, and logs that hold no conversation at all (agy start-up
only, like the app's 30 s ``agy models`` checks). The user's own conversations stay.
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path

DATA = Path.home() / ".gemini" / "antigravity-cli"
LOG_HEAD = 64 * 1024  # bytes of a log read to find its workspace
_APP_WORKSPACE = re.compile(
    r"(/paper-pile/agy/?$)|(/pp-qa-agy-[^/]+/)|(^/tmp/claude-[^/]+/[^/]*paper-pile[^/]*/)"
)
_LOG_WORKSPACE = re.compile(rb"workspaceDirs=\[([^\]]*)\]")
_CONVERSATION_IN_LOG = (  # a log with any of these had a real session (keep the user's)
    b"planner_response",
    b"user_input",
    b"text_delta",
    b"streamGenerate",
    b"convID=",
    b"for conversation ",
)


def app_workspace(uri_or_path: str) -> bool:
    path = uri_or_path.removeprefix("file://")
    return bool(path) and bool(_APP_WORKSPACE.search(path))


def agy_running() -> list[int]:
    """Live ``agy`` processes of this user (any of them may rewrite these files)."""
    out = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            exe = os.readlink(proc / "exe")
        except OSError:
            continue
        if Path(exe).name == "agy":
            out.append(int(proc.name))
    return out


def app_conversations(db: Path) -> set[str]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute("select conversation_id, workspace_uris from conversation_summaries")
        found = set()
        for cid, uris in rows:
            try:
                listed = json.loads(uris or "[]")
            except ValueError:
                listed = [uris]
            if any(app_workspace(str(u)) for u in listed):
                found.add(str(cid))
        return found
    finally:
        con.close()


def metadata_ids(meta: Path) -> set[str]:
    try:
        convs = json.loads(meta.read_text(encoding="utf-8")).get("conversations", {})
    except (OSError, ValueError):
        return set()
    return {
        cid
        for cid, entry in convs.items()
        if any(app_workspace(str(u)) for u in entry.get("summary", {}).get("WorkspaceURIs", []))
    }


def app_logs(logs: Path) -> list[Path]:
    out = []
    for f in sorted(logs.glob("*.log")) if logs.is_dir() else []:
        if f.is_symlink():
            continue
        try:
            with f.open("rb") as fh:
                head = fh.read(LOG_HEAD)
            body = f.read_bytes() if f.stat().st_size <= 4 * 1024 * 1024 else head
        except OSError:
            continue
        m = _LOG_WORKSPACE.search(head)
        spaces = [s.strip().decode("utf-8", "replace") for s in m.group(1).split()] if m else []
        if any(app_workspace(s) for s in spaces) or not any(
            k in body for k in _CONVERSATION_IN_LOG
        ):
            out.append(f)
    return out


def conversation_files(cid: str) -> list[Path]:
    paths = [DATA / "conversations" / f"{cid}{ext}" for ext in (".db", ".db-wal", ".db-shm")] + [
        DATA / "annotations" / f"{cid}.pbtxt",
        DATA / "presence" / f"{cid}.lock",
    ]
    return [p for p in paths if p.exists()] + (
        [DATA / "brain" / cid] if (DATA / "brain" / cid).is_dir() else []
    )


def write_json(path: Path, data: object) -> None:
    tmp = path.with_suffix(path.suffix + ".pp-tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="remove (default: dry run)")
    args = parser.parse_args()
    db = DATA / "conversation_summaries.db"
    meta = DATA / "cache" / "conversation_metadata.json"
    last = DATA / "cache" / "last_conversations.json"
    jetbox = DATA / "jetbox_summaries_proto.pb"
    if not db.exists():
        print(f"No Antigravity CLI data at {DATA}.")
        return 0
    ids = app_conversations(db) | metadata_ids(meta)
    files = [p for cid in sorted(ids) for p in conversation_files(cid)]
    logs = app_logs(DATA / "log")
    try:
        last_map = json.loads(last.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        last_map = {}
    last_keys = [k for k in last_map if app_workspace(k)]
    log_bytes = sum(f.stat().st_size for f in logs)
    print(f"App conversations (summaries + metadata): {len(ids)}")
    print(f"Their conversation / brain / annotation / presence files: {len(files)}")
    print(f"Log files (app workspaces, or start-up only): {len(logs)} ({log_bytes / 1e6:.0f} MB)")
    print(f"last_conversations entries: {len(last_keys)}")
    print(f"jetbox_summaries_proto.pb: {'rebuilt by agy' if jetbox.exists() else 'none'}")
    if not args.apply:
        print("\nDry run: nothing removed. Run with --apply (with no agy running).")
        return 0
    running = agy_running()
    if running:
        print(f"\nagy is running (pids {running}): close it (and paper-pile) first.")
        return 1
    con = sqlite3.connect(db)
    try:
        con.execute("PRAGMA secure_delete = ON")
        marks = ",".join("?" * len(ids))
        if ids:
            con.execute(
                f"delete from conversation_summaries where conversation_id in ({marks})",
                sorted(ids),
            )
            con.execute(
                f"delete from conversations_fts where conversation_id in ({marks})", sorted(ids)
            )
        con.commit()
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.execute("VACUUM")  # deleted text must not stay in free pages
    finally:
        con.close()
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        for cid in ids:
            data.get("conversations", {}).pop(cid, None)
        write_json(meta, data)
    except (OSError, ValueError) as exc:
        print(f"metadata not changed: {exc}")
    if last_keys:
        for k in last_keys:
            last_map.pop(k, None)
        write_json(last, last_map)
    for p in files:
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)
    for f in logs:
        f.unlink(missing_ok=True)
    jetbox.unlink(missing_ok=True)
    print("\nRemoved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
