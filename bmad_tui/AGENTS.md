# BMAD Dashboard TUI — Agent Reference

This document explains the `tools/bmad_tui` package to AI agents that need to understand, extend, or debug it.

---

## What it is

A terminal-based mission-control dashboard for managing a BMAD sprint. It reads `_bmad-output/implementation-artifacts/sprint-status.yaml`, renders the epic/story backlog in a Rich TUI, and lets the user dispatch BMAD agent workflows directly from the terminal without leaving the repo.

Run from the repo root:

```bash
python -m tools.bmad_tui
```

If `sprint-status.yaml` does not exist yet, an interactive wizard runs first to bootstrap the project (PRD → Architecture → Epics & Stories → Sprint Planning).

---

## Module map

| File | Purpose |
|---|---|
| `__main__.py` | Entry point. Bootstraps project if needed, then starts the dashboard. |
| `dashboard.py` | Rich `App` subclass — the full TUI. Renders epics, stories, action panel, model picker, history. |
| `state.py` | Parses `sprint-status.yaml` into `ProjectState`. |
| `models.py` | Pure data classes: `Story`, `Epic`, `WorkflowDef`, `AgentDef`, `Model`, `StoryStatus`. |
| `workflows.py` | Registry of every `WorkflowDef` keyed by `workflow_key` string. Defines agent IDs, prompt templates, default models. |
| `agent_runner.py` | Spawns CLI agent sessions via the `expect` script. Handles session logging, session-ID tracking, CR loop iteration, and history capture. |
| `session.expect` | Tcl/Expect script that wraps the CLI binary (copilot or claude) in a PTY, handles idle detection, task-done chime, and auto-despawn. |
| `config.py` | Persists per-project TUI preferences to `.bmad-tui-config.json` (model memory, auto-despawn, CLI tool choice). |
| `wizard.py` | New-project bootstrap: walks PRD → Architecture → Epics → Sprint Planning, skipping already-completed steps. |
| `history.py` | Appends and reads session history entries for the in-TUI history panel. |
| `kitty_graphics.py` | Optional Kitty terminal graphics protocol helpers (not required for core function). |

---

## How agent sessions work

`agent_runner.run_workflow()` is the single entrypoint for launching any agent:

1. Resolves the `WorkflowDef` from `WORKFLOWS[workflow_key]`.
2. Formats the prompt template with `{story_id}`, `{story_path}`, `{sprint_status_path}`, `{epic_id}`.
3. Calls `expect -f session.expect` with positional args:

   ```
   <model> <agent> <prompt> <repo_root> <idle_secs> <session_id> <log_file> <is_yolo> <auto_despawn> <cli_tool>
   ```

4. The expect script spawns either `copilot` or `claude` (see CLI tool section below).
5. When the session ends, `_extract_session_info()` parses the log for the resume UUID and stats (usage, time, code changes).
6. A `HistoryEntry` is returned and persisted by the caller.

### Session modes

| Mode | Trigger | Idle timer | Notes |
|---|---|---|---|
| **Yolo** | `from_menu=False` (story action) | Active — kills agent after task-done + idle | Agent receives prompt immediately, skips menu |
| **Interactive** | `from_menu=True` (agent launcher) | Disabled — user exits manually | No prompt injected; agent shows its own menu |

`auto_despawn` can be toggled globally via the TUI settings. When enabled in yolo mode, the expect script sends `/exit` + Ctrl-D to the CLI after the task-done chime fires and at least one file change is detected.

### CR Loop

The `code-review` workflow runs `_run_cr_loop()` instead of a single session. It iterates up to `MAX_CR_ITERS` (10) times, checking after each pass whether the findings file contains `"CLEAN — zero findings"` or whether a new commit appeared. This mirrors the logic of `tools/cr-loop/cr-loop.sh`.

---

## Workflows registry (`workflows.py`)

Each entry in `WORKFLOWS` has:

- `label` — display name in the TUI
- `agent` — Copilot/Claude agent ID (e.g. `bmad-agent-bmm-dev`)
- `persona` — short human-readable name shown in history
- `default_model` — `Model` enum value used unless overridden
- `model_locked` — if `True`, model cannot be changed (used for CR Loop → `gpt-5.3-codex`)
- `prompt_template` — string with `{story_id}`, `{story_path}`, `{sprint_status_path}`, `{epic_id}` placeholders
- `bmad_phase` — one of the canonical phases: Analysis, Planning, UX, Implementation, QA, Documentation, Creative & Meta

Key workflow keys: `dev-story`, `code-review`, `create-story`, `validate-story`, `sprint-planning`, `create-prd`, `create-architecture`, `create-epics-and-stories`, and more. Check `workflows.py` for the full list.

---

## Models

Defined in `models.py` as `Model(str, Enum)`:

| Value | Label | Use |
|---|---|---|
| `claude-sonnet-4.6` | `sonnet-4.6` | Default for all coding / planning |
| `claude-opus-4.6` | `opus-4.6` | Deeper reasoning for complex sessions |
| `gpt-5.3-codex` | `codex-5.3` | Pre-assigned to CR Loop — not overridable |

---

## CLI tool support: `copilot` vs `claude`

The TUI supports two CLI backends, selected at first launch and saved in `.bmad-tui-config.json` (`cli_tool` key):

- **`copilot`** — GitHub Copilot CLI. **Primary, fully tested.** Spawned with `--allow-all-tools --alt-screen off --interactive`.
- **`claude`** — Anthropic Claude CLI. **⚠️ Integration is untested and may need work.** The expect script spawns it with `--dangerously-skip-permissions` and `--add-dir`. Session-ID tracking looks for `~/.claude/projects/<uuid>.jsonl` files instead of the Copilot session-state directories. The task-done chime detection (`ESC]9;4;0`) and idle-timer logic assume the same PTY signals that Copilot emits — Claude's CLI may behave differently.

If you need to add or fix Claude CLI support, the main integration points are:

1. `session.expect` — the `if {$cli_tool eq "claude"}` branch (spawning and flag differences).
2. `agent_runner._find_latest_session_id()` — the `cli_tool == "claude"` branch (`.jsonl` file detection).
3. `agent_runner.available_clis()` — lists installed CLIs; runs `shutil.which("claude")`.
4. The task-done chime pattern (`ESC]9;4;0;0 BEL`) — verify Claude emits this; if not, the idle/auto-despawn logic will not fire correctly.

---

## Prerequisites

- Python ≥ 3.11 with packages from `requirements.txt` (Rich, PyYAML, etc.)
- `expect` — `brew install expect`
- At least one of: `copilot` CLI (`npm install -g @github/copilot-cli`) or `claude` CLI

Check with:

```bash
python -m tools.bmad_tui  # prerequisite check runs at startup
```

---

## Key bindings (dashboard)

| Key | Action |
|---|---|
| `↑ ↓` | Navigate stories |
| `Enter` | Open action panel for selected story |
| `Space` | Preview story file |
| `r` | Refresh sprint status |
| `1`–`6` | Jump to filter: All / In Progress / Review / Ready / Needs Story / Done |
| `f` | Cycle status filter |
| `s` | Run sprint-planning |
| `a` | Open agent launcher |
| `q` | Quit |

---

## State file

`sprint-status.yaml` (under `_bmad-output/implementation-artifacts/`) is the source of truth for epic and story statuses. The TUI reads it on launch and on `r` refresh. It does not write to it directly — agents update it as part of story execution.

Story `effective_status` is derived in `models.Story.effective_status`: a `backlog` story with no `.md` file becomes `needs-story`; with a file it becomes `ready-for-dev`.
