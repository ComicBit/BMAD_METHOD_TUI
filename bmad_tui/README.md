# BMAD Dashboard TUI

A terminal mission-control interface for BMAD sprint management.

## Install

```bash
./install.sh
```

Also requires:
- [GitHub Copilot CLI](https://docs.github.com/en/copilot/github-copilot-in-the-cli) (`npm install -g @github/copilot-cli`)
- `expect` — `brew install expect`

## Run

From the repo root:

```bash
tui
```

## Key bindings

| Key | Action |
|-----|--------|
| `↑ ↓` | Navigate stories |
| `Enter` | Open action panel for selected story |
| `Space` | Preview story file (read ACs before acting) |
| `r` | Refresh sprint status |
| `1`–`6` | Jump directly to filter: 1=All, 2=In Progress, 3=Review, 4=Ready, 5=Needs Story, 6=Done |
| `f` | Cycle status filter (backward-compatible) |
| `s` | Run sprint-planning |
| `a` | Open agent launcher |
| `q` | Quit |

## Model selection

In the action panel, use the model dropdown to pick:
- `claude-sonnet-4.6` — default for all coding / planning
- `claude-opus-4.6` — deeper reasoning for complex sessions
- `gpt-5.3-codex` — pre-assigned to CR Loop (not overridable)

## New project

If no `sprint-status.yaml` exists, the wizard runs first:
PRD → Architecture → Epics & Stories → Sprint Planning.
Each step spawns the right Copilot agent. Already-completed steps are skipped.
