"""Workflow run history — JSONL persistence and loader."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


_LOG_PATH = Path("artifacts") / "logs" / "tui-history.jsonl"
_MAX_ENTRIES = 100


@dataclass
class HistoryEntry:
    ts: str
    workflow: str
    agent: str
    model: str
    story_id: str
    epic_id: str
    branch: str = ""
    session_id: str = ""
    usage_est: str = ""
    api_time: str = ""
    session_time: str = ""
    code_changes: str = ""
    task_name: str = ""  # human-readable story title or empty for non-story runs


def _log_path(project_root: Path) -> Path:
    return project_root / _LOG_PATH


def append_history(project_root: Path, entry: HistoryEntry) -> None:
    """Append a structured entry to the workflow history log."""
    log = _log_path(project_root)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry.__dict__) + "\n")


def purge_legacy_entries(project_root: Path) -> int:
    """Remove all history entries that predate session_id capture (session_id == "").

    Called once at TUI startup to clear pre-feature history.
    Returns the number of entries removed.
    """
    log = _log_path(project_root)
    if not log.exists():
        return 0
    entries = load_history(project_root)
    kept = [e for e in entries if e.session_id]
    removed = len(entries) - len(kept)
    if removed == 0:
        return 0
    if kept:
        log.write_text(
            "\n".join(json.dumps(e.__dict__) for e in kept) + "\n",
            encoding="utf-8",
        )
    else:
        log.unlink()
    return removed


_ZERO_CHANGE_PATTERNS = frozenset(("", "+0 -0", "0"))


def has_zero_code_changes(entry: HistoryEntry) -> bool:
    """Return True when the entry recorded no code changes.

    Used to suppress the history-title prompt for sessions that ran but made
    no file modifications (e.g. research / chat-only runs).
    """
    return entry.code_changes in _ZERO_CHANGE_PATTERNS


def is_trivial_entry(entry: HistoryEntry) -> bool:
    """Return True for sessions that produced no meaningful work.

    ``api_time == "0s"`` means zero API calls this run — the only reliable
    signal across both new and resumed sessions.  For resumed sessions copilot
    reports the *cumulative* code_changes of the original session even when
    nothing new was done, so we never use code_changes as a disqualifier.

    When stats weren't captured at all (api_time empty) we fall back to
    requiring code_changes to also be empty/zero.
    """
    if entry.api_time == "0s":
        return True
    if entry.api_time == "" and entry.code_changes in ("", "+0 -0", "0"):
        return True
    return False


def purge_trivial_entries(project_root: Path) -> int:
    """Remove history entries that represent abandoned/empty sessions.

    Returns the number of entries removed.
    """
    log = _log_path(project_root)
    if not log.exists():
        return 0
    entries = load_history(project_root)
    kept = [e for e in entries if not is_trivial_entry(e)]
    removed = len(entries) - len(kept)
    if removed == 0:
        return 0
    if kept:
        log.write_text(
            "\n".join(json.dumps(e.__dict__) for e in kept) + "\n",
            encoding="utf-8",
        )
    else:
        log.unlink()
    return removed


def load_history(project_root: Path) -> list[HistoryEntry]:
    """Load the last _MAX_ENTRIES workflow history entries."""
    log = _log_path(project_root)
    if not log.exists():
        return []
    entries: list[HistoryEntry] = []
    for line in log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            entries.append(HistoryEntry(
                ts=d.get("ts", ""),
                workflow=d.get("workflow", ""),
                agent=d.get("agent", ""),
                model=d.get("model", ""),
                story_id=d.get("story_id", ""),
                epic_id=d.get("epic_id", ""),
                branch=d.get("branch", ""),
                session_id=d.get("session_id", ""),
                usage_est=d.get("usage_est", ""),
                api_time=d.get("api_time", ""),
                session_time=d.get("session_time", ""),
                code_changes=d.get("code_changes", ""),
                task_name=d.get("task_name", ""),
            ))
        except (json.JSONDecodeError, TypeError):
            pass
    return entries[-_MAX_ENTRIES:]
