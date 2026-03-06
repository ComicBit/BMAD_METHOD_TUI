"""Spawn Copilot agent sessions via the expect script."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .history import HistoryEntry, is_trivial_entry
from .models import Model, ProjectState, Story, WorkflowDef
from .workflows import WORKFLOWS


_EXPECT_SCRIPT = Path(__file__).parent / "session.expect"

# CR loop runs shorter idle timeout to match its original behaviour
_IDLE_SECS: dict[str, int] = {
    "code-review": 90,
}
_DEFAULT_IDLE_SECS = 180

# Maximum number of CR loop iterations (mirrors cr-loop.sh MAX_ITERS)
MAX_CR_ITERS = 10

_SESSION_ID_RE = re.compile(
    r"--resume[= ]([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

_STATS_RES: dict[str, re.Pattern[str]] = {
    "usage_est":    re.compile(r"Total usage est:\s+(.+?)[\r\n]"),
    "api_time":     re.compile(r"API time spent:\s+(.+?)[\r\n]"),
    "session_time": re.compile(r"Total session time:\s+(.+?)[\r\n]"),
    "code_changes": re.compile(r"Total code changes:\s+(.+?)[\r\n]"),
}


def _run_and_cleanup(cmd: list[str], cli_tool: str = "copilot") -> None:
    """Run *cmd* synchronously and wait for it to finish.

    expect must run in the current session so its ``interact`` command retains
    the controlling terminal — required for copilot I/O to work correctly.
    No external process killing is needed: for yolo/CR sessions the expect
    idle timer sends ``/exit`` + Ctrl-D *to copilot* (inside the PTY), which
    lets it exit gracefully; for interactive sessions the user exits manually.
    """
    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        # expect's interact already forwarded Ctrl+C to the PTY; just return.
        pass


def _find_latest_session_id(
    started_after: float,
    cli_tool: str = "copilot",
    _sessions_dir: Path | None = None,
) -> str:
    """Return the UUID of the session created/modified after *started_after*.

    For copilot: watches ``~/.copilot/session-state/<uuid>/`` directories.
    For claude:  watches ``~/.claude/projects/<uuid>.jsonl`` files.
    *_sessions_dir* is exposed only for unit-testing.
    """
    if cli_tool == "claude":
        sessions_dir = _sessions_dir or (Path.home() / ".claude" / "projects")
        if not sessions_dir.exists():
            return ""
        try:
            best: tuple[float, str] | None = None
            for f in sessions_dir.iterdir():
                if not f.is_file() or f.suffix != ".jsonl":
                    continue
                mtime = f.stat().st_mtime
                if mtime > started_after:
                    if best is None or mtime > best[0]:
                        best = (mtime, f.stem)
            return best[1] if best else ""
        except Exception:
            return ""

    # copilot: directory-based session storage
    sessions_dir = _sessions_dir or (Path.home() / ".copilot" / "session-state")
    if not sessions_dir.exists():
        return ""
    try:
        best = None
        for d in sessions_dir.iterdir():
            if not d.is_dir():
                continue
            mtime = d.stat().st_mtime
            if mtime > started_after:
                if best is None or mtime > best[0]:
                    best = (mtime, d.name)
        return best[1] if best else ""
    except Exception:
        return ""


def _extract_session_info(log_path: Path) -> dict[str, str]:
    """Parse a copilot session log for the resume UUID and summary stats."""
    result: dict[str, str] = {
        "session_id":   "",
        "usage_est":    "",
        "api_time":     "",
        "session_time": "",
        "code_changes": "",
    }
    try:
        raw = log_path.read_bytes().decode("utf-8", errors="replace")
        text = _ANSI_RE.sub("", raw)
        ids = _SESSION_ID_RE.findall(text)
        if ids:
            result["session_id"] = ids[-1]
        for key, pattern in _STATS_RES.items():
            m = pattern.search(text)
            if m:
                result[key] = m.group(1).strip()
    except Exception:
        pass
    return result


def _extract_session_id(log_path: Path) -> str:
    """Parse a copilot log file for a --resume=<uuid> line; return the last UUID found."""
    return _extract_session_info(log_path)["session_id"]


def _cr_findings_path(project_root: Path) -> Path:
    """Derive the findings file path from the current git branch (mirrors cr-loop.sh)."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=False, cwd=str(project_root),
    )
    branch = result.stdout.strip()
    # e.g. US7/US7.2 → us7_2  (same transform as cr-loop.sh)
    story_slug = branch.split("/")[-1].lower().replace(".", "_")
    return project_root / "artifacts" / "logs" / "cr-loop" / f"findings_{story_slug}.md"


def _current_branch(project_root: Path) -> str:
    """Return the current git branch for history display."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(project_root),
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _run_cr_loop(cmd: list[str], project_root: Path, cli_tool: str = "copilot") -> None:
    """Run the CR session up to MAX_CR_ITERS times, mirroring cr-loop.sh logic.

    Each iteration:
      1. Records HEAD before the session.
      2. Runs one expect session (agent does Phase 1 audit + Phase 2 fix).
      3. Stops if the findings file contains the CLEAN signal.
      4. Loops for a verification pass if a new commit appeared; stops otherwise.
    Kills any lingering CLI processes when done.
    """
    findings_path = _cr_findings_path(project_root)
    (project_root / "artifacts" / "logs" / "cr-loop").mkdir(parents=True, exist_ok=True)

    def _git_head() -> str:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False, cwd=str(project_root),
        )
        return r.stdout.strip()

    for i in range(1, MAX_CR_ITERS + 1):
        print(f"\n===== CR iteration {i}/{MAX_CR_ITERS} =====", flush=True)
        before = _git_head()

        _run_and_cleanup(cmd, cli_tool)

        after = _git_head()

        if findings_path.exists() and "CLEAN — zero findings" in findings_path.read_text():
            print("✅ Findings file reports CLEAN. Stopping.", flush=True)
            break

        if after != before:
            print(f"✅ New commit: {before[:8]} → {after[:8]}. Verification pass...", flush=True)
            continue

        print("✅ No new commit. Stopping.", flush=True)
        break
    else:
        print(f"⚠️  Reached max CR iterations ({MAX_CR_ITERS}) without stabilising.", flush=True)


def available_clis() -> list[str]:
    """Return a list of installed CLI tools that can run agent sessions."""
    return [cli for cli in ("copilot", "claude") if shutil.which(cli)]


def check_prerequisites() -> list[str]:
    """Return a list of missing prerequisite tool names.

    Returns an error only if *no* supported CLI is installed, plus if expect is missing.
    """
    missing = []
    if not available_clis():
        missing.append("copilot or claude")
    if not shutil.which("expect"):
        missing.append("expect")
    return missing


def run_workflow(
    workflow_key: str,
    state: ProjectState,
    model: Model,
    story: Story | None = None,
    epic_id: str | None = None,
    session_id: str = "",
    from_menu: bool = False,
    auto_despawn: bool = False,
    cli_tool: str = "copilot",
    task_name: str = "",
) -> HistoryEntry | None:
    """Spawn a CLI agent session for the given workflow.

    Blocks until the session exits (the expect script handles idle detection).
    Returns the HistoryEntry for the caller to persist (after optionally labelling
    it), or None when the session was trivial (no API calls / no work done).

    Pass ``session_id`` to resume an existing session via ``--resume``.

    ``from_menu=True`` → "slow/interactive" mode: the idle timer is disabled so
    the user controls when to exit.  ``from_menu=False`` → "yolo" mode: the idle
    timer fires after the task-done chime *if* ``auto_despawn`` is True and the
    worktree shows at least one change since the session started.
    ``cli_tool`` selects which CLI binary to spawn: "copilot" (default) or "claude".
    """
    wf: WorkflowDef = WORKFLOWS[workflow_key]
    actual_model = wf.default_model if wf.model_locked else model

    story_id = story.id if story else ""
    story_slug = story_id.replace("-", "_").replace("/", "_").lower()
    story_path = str(story.file_path) if (story and story.file_path) else ""
    epic = epic_id or (story.epic_id if story else "")
    task_name = task_name or (story.doc_title if story else "")

    prompt = wf.prompt_template.format(
        story_id=story_id,
        story_slug=story_slug,
        story_path=story_path,
        sprint_status_path=str(state.sprint_status_path),
        epic_id=epic,
        **{"project-root": str(state.project_root)},
    )

    if from_menu:
        prompt = ""

    # is_yolo: True when agent receives a prompt and proceeds immediately (no interactive menu).
    # Slow/interactive sessions (from_menu=True) never get an idle kill timer.
    is_yolo = not from_menu

    idle_secs = _IDLE_SECS.get(workflow_key, _DEFAULT_IDLE_SECS)

    before_ts = time.time()

    fd, log_file_path = tempfile.mkstemp(suffix=".log", prefix="copilot_session_")
    os.close(fd)
    log_path = Path(log_file_path)

    cmd = [
        "expect", "-f", str(_EXPECT_SCRIPT),
        "--",
        actual_model.value,
        wf.agent,
        prompt if not session_id else "",
        str(state.project_root),
        str(idle_secs),
        session_id,            # arg 5: non-empty triggers --resume in expect script
        log_file_path,         # arg 6: log file for stats capture
        "1" if is_yolo else "0",                     # arg 7: is_yolo
        "1" if (is_yolo and auto_despawn) else "0",  # arg 8: auto_despawn
        cli_tool,                                    # arg 9: cli binary name
    ]

    if workflow_key == "code-review":
        _run_cr_loop(cmd, state.project_root, cli_tool)
    else:
        _run_and_cleanup(cmd, cli_tool)

    captured = _extract_session_info(log_path)
    try:
        log_path.unlink()
    except Exception:
        pass

    # Session ID priority:
    # 1. session_id  — for resumes we already know it.
    # 2. captured["session_id"] — parsed from this session's own log output
    #    (the "Resume with copilot --resume=<uuid>" line Copilot prints at exit).
    #    This is project-specific and unambiguous.
    # 3. _find_latest_session_id — filesystem fallback; scans ALL sessions by
    #    mtime and can return a concurrent session from a different project, so
    #    it is only used when log parsing yields nothing.
    new_session_id = session_id or captured["session_id"] or _find_latest_session_id(before_ts, cli_tool)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = HistoryEntry(
        ts=ts,
        workflow=workflow_key,
        agent=wf.agent,
        model=actual_model.value,
        story_id=story_id,
        epic_id=epic,
        branch=_current_branch(state.project_root),
        session_id=new_session_id,
        usage_est=captured["usage_est"],
        api_time=captured["api_time"],
        session_time=captured["session_time"],
        code_changes=captured["code_changes"],
        task_name=task_name,
    )
    if is_trivial_entry(entry):
        return None
    return entry
