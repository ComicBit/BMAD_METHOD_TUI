<h1 align="center">
  <br>
  BMAD Dashboard TUI
  <br>
</h1>

<p align="center">
  <strong>Terminal mission control for BMAD projects.</strong><br>
  Story board · agent launcher · bootstrap wizard · session history
</p>

<p align="center">
  <img alt="Platform" src="https://img.shields.io/badge/Platform-Terminal-111111">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="UI" src="https://img.shields.io/badge/UI-Textual-5A67D8">
  <img alt="Config" src="https://img.shields.io/badge/State-YAML%20%2B%20JSON-0F766E">
  <img alt="Status" src="https://img.shields.io/badge/Status-Prototype%20%2F%20Extraction-yellow">
</p>

---

## What It Does

BMAD Dashboard TUI is a terminal interface for operating a repository that follows the BMAD workflow. It reads BMAD planning and implementation artifacts from the repo, renders the sprint as epics and stories, and lets you launch the right BMAD agent workflow without leaving the terminal.

The core loop is simple:

1. Read `_bmad-output/implementation-artifacts/sprint-status.yaml`
2. Derive story state from YAML plus the presence of story markdown files
3. Show the backlog as a navigable Textual dashboard
4. Launch the appropriate agent session for the selected story or phase
5. Record session metadata so work can be resumed or audited later

This project is effectively a standalone extraction of the BMAD TUI used in other repos such as Aurora and Zoe Validator.

---

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────┐
│                         BMAD Dashboard TUI                         │
│                                                                     │
│  ┌──────────────────┐   ┌────────────────────┐   ┌───────────────┐  │
│  │  Sprint View     │   │  Story Action      │   │ Agent Picker  │  │
│  │  epics + cards   │   │  workflow chooser  │   │ phase/persona │  │
│  └────────┬─────────┘   └─────────┬──────────┘   └──────┬────────┘  │
│           │                       │                       │           │
│           └──────────────┬────────┴──────────────┬────────┘           │
│                          ▼                       ▼                    │
│                  ProjectState loader       Workflow registry          │
│                  status derivation         prompts + models           │
└──────────────────────────┬───────────────────────┬────────────────────┘
                           │                       │
                           ▼                       ▼
                _bmad-output artifacts      Expect session runner
                epics.md / stories /        copilot or claude CLI
                sprint-status.yaml          session logs + resume IDs
                           │                       │
                           └──────────────┬────────┘
                                          ▼
                                History + local config
                          artifacts/logs/tui-history.jsonl
                          .bmad-tui-config.json
```

### Core Components

| Component | Role |
|-----------|------|
| `bmad_tui/dashboard.py` | Main Textual app: story board, detail pane, history, modals, launcher UI |
| `bmad_tui/state.py` | Parses BMAD artifacts into a `ProjectState` with epics, stories, and derived status |
| `bmad_tui/workflows.py` | Central registry of BMAD workflows, agents, prompt templates, models, and phases |
| `bmad_tui/agent_runner.py` | Starts agent sessions through `expect`, captures resume IDs, tracks run stats, handles CR loop |
| `bmad_tui/wizard.py` | Bootstrap flow for new projects: PRD → Architecture → Epics & Stories → Sprint Planning |
| `bmad_tui/history.py` | Persists run history to JSONL and filters trivial or legacy entries |
| `bmad_tui/config.py` | Stores per-project preferences such as remembered models and CLI selection |
| `bmad_tui/session.expect` | PTY wrapper for Copilot or Claude CLI, including idle handling and auto-despawn |

---

## Product Shape

### Primary capabilities

- Render the current sprint directly from BMAD output files
- Distinguish `needs-story`, `ready-for-dev`, `in-progress`, `review`, `done`, and blocked work
- Launch story-specific workflows such as create story, dev story, code review, and course correction
- Launch global workflows for planning, architecture, research, QA, documentation, and quick flows
- Bootstrap a new BMAD repo when `sprint-status.yaml` does not exist yet
- Track workflow history with timestamps, model used, session ID, API time, and code-change stats
- Resume or rerun prior sessions from the dashboard

### Workflow model

The registry groups work under BMAD-style phases:

- `Analysis`
- `Planning`
- `UX`
- `Implementation`
- `QA`
- `Documentation`
- `Creative & Meta`

Representative workflows currently defined in code include:

- `create-prd`
- `create-architecture`
- `create-epics-and-stories`
- `sprint-planning`
- `create-story`
- `validate-story`
- `dev-story`
- `code-review`
- `correct-course`
- `technical-research`
- `qa-automate`
- `document-project`
- `quick-dev`
- `quick-spec`

### Model policy

Three model values are built into the app:

| Model | Intended use |
|-------|--------------|
| `claude-sonnet-4.6` | Default for planning and implementation |
| `claude-opus-4.6` | Deeper reasoning for more complex sessions |
| `gpt-5.3-codex` | Locked for CR Loop / code review workflow |

---

## Repo Inputs And Outputs

### Reads from the repository

- `_bmad-output/planning-artifacts/prd.md`
- `_bmad-output/planning-artifacts/architecture.md`
- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `_bmad-output/implementation-artifacts/*.md` story files

### Writes inside the repository

- `artifacts/logs/tui-history.jsonl`
- `artifacts/logs/cr-loop/findings_<story>.md`
- `.bmad-tui-config.json`

The TUI itself treats `sprint-status.yaml` as the source of truth. Agent sessions are expected to mutate project artifacts; the dashboard mostly reads and routes.

---

## Current Status

This standalone repo is not fully normalized yet. The implementation and tests still contain historical references to `tools.bmad_tui`, while the code in this checkout lives under `bmad_tui/`.

That means:

- The project is well-defined architecturally
- The README can document the intended behavior accurately
- The launcher/import path still needs cleanup before the standalone package runs cleanly as-is

During verification in this checkout:

- `bmad_tui` is importable as a package
- `tools.bmad_tui` is not present
- `python3 -m pytest ...` currently fails at collection because tests import `tools.bmad_tui.*`
- `from bmad_tui.__main__ import main` also fails for the same reason

So treat this repository today as a focused code extraction plus tests and docs, not yet a polished standalone release.

---

## Requirements

### Runtime dependencies

| Requirement | Purpose |
|-------------|---------|
| Python 3.11+ | Runs the TUI and helper modules |
| `textual` | Terminal UI framework |
| `pyyaml` | Parses `sprint-status.yaml` |
| `pyfiglet` | Small presentation/CLI helper dependency |
| `expect` | Required for interactive CLI session orchestration |
| `copilot` or `claude` CLI | Actual BMAD agent backend |

### Python packages

Install from [`bmad_tui/requirements.txt`](/Users/comicbit/Projects/BMAD_METHOD_TUI/bmad_tui/requirements.txt):

```bash
python3 -m pip install -r bmad_tui/requirements.txt
```

If you want to run the test suite after the import-path cleanup, install `pytest` as well:

```bash
python3 -m pip install pytest
```

### External CLIs

- GitHub Copilot CLI: `npm install -g @github/copilot-cli`
- Or Anthropic Claude CLI if you want to exercise the alternate backend
- `expect`: `brew install expect`

Copilot appears to be the primary and more fully exercised target in the current implementation.

---

## Getting Started

Because this repo still has namespace drift, there are two different notions of "getting started":

### 1. Understand the system today

Read these files first:

- [`bmad_tui/dashboard.py`](/Users/comicbit/Projects/BMAD_METHOD_TUI/bmad_tui/dashboard.py)
- [`bmad_tui/workflows.py`](/Users/comicbit/Projects/BMAD_METHOD_TUI/bmad_tui/workflows.py)
- [`bmad_tui/agent_runner.py`](/Users/comicbit/Projects/BMAD_METHOD_TUI/bmad_tui/agent_runner.py)
- [`bmad_tui/state.py`](/Users/comicbit/Projects/BMAD_METHOD_TUI/bmad_tui/state.py)
- [`bmad_tui/wizard.py`](/Users/comicbit/Projects/BMAD_METHOD_TUI/bmad_tui/wizard.py)

### 2. Prepare it for local execution

The code currently expects to be imported as `tools.bmad_tui`. To run it as a standalone repo, the import namespace and launcher scripts need to be aligned first.

Once that cleanup is done, the intended flow is:

```bash
python3 -m pip install -r bmad_tui/requirements.txt
python3 -m <normalized-entrypoint>
```

The bootstrap wizard is designed to run automatically when no sprint status exists:

```text
Create PRD
  → Create Architecture
  → Create Epics & Stories
  → Sprint Planning
```

---

## Key Interactions

The dashboard tests and docs describe these main bindings:

| Key | Action |
|-----|--------|
| `↑ ↓` | Navigate stories |
| `Enter` | Open story action modal |
| `Space` | Preview story markdown |
| `r` | Refresh state from BMAD artifacts |
| `f` | Cycle status filter |
| `1`-`6` | Jump to common filters |
| `s` | Run sprint planning |
| `a` | Open agent launcher |
| `m` | Change model |
| `h` | Open history |
| `q` | Quit |

---

## Project Layout

```text
BMAD_METHOD_TUI/
├── README.md
├── bmad-tui.sh
└── bmad_tui/
    ├── __main__.py
    ├── dashboard.py
    ├── agent_runner.py
    ├── workflows.py
    ├── state.py
    ├── models.py
    ├── wizard.py
    ├── history.py
    ├── config.py
    ├── session.expect
    ├── install.sh
    ├── requirements.txt
    └── tests/
```

---

## Why This Project Matters

Most BMAD workflows are powerful but fragmented across prompts, markdown artifacts, and external agent CLIs. This TUI tries to give that system an operational surface:

- one dashboard instead of scattered files
- one place to choose the next workflow
- one record of what was run, with which model, and whether it can be resumed
- one onboarding path for new BMAD projects

That is the right product direction. The next step for this repo is not redefining the concept; it is finishing the extraction so the standalone package, scripts, and tests all agree on a single import path.
