"""Entry point: python -m bmad_tui."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as `python -m bmad_tui` from repo root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from bmad_tui.dashboard import Dashboard
from bmad_tui.state import find_project_root, load_state
from bmad_tui.wizard import run_wizard_if_needed


def main() -> None:
    project_root = find_project_root()
    state = load_state(project_root)

    # New project bootstrap: if no sprint-status.yaml, run wizard first
    if not state.sprint_status_path.exists():
        completed = run_wizard_if_needed(project_root)
        if not completed:
            print("Wizard cancelled. Exiting.")
            sys.exit(0)

    app = Dashboard(project_root)
    app.run()


if __name__ == "__main__":
    main()
