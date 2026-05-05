"""Entry point: python -m bmad_tui."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as `python -m bmad_tui` from repo root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from bmad_tui.dashboard import Dashboard
from bmad_tui.state import find_project_root


def main() -> None:
    project_root = find_project_root()
    app = Dashboard(project_root)
    app.run()


if __name__ == "__main__":
    main()
