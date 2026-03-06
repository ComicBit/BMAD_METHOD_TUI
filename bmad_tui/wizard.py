"""New project bootstrap wizard.

Runs before the main dashboard when no sprint-status.yaml exists.
Walks through PRD → Architecture → Epics & Stories → Sprint Planning.
Each step is skipped if the expected output file already exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .agent_runner import check_prerequisites, run_workflow
from .models import Model, ProjectState, Story
from .state import load_state
from .workflows import WORKFLOWS


@dataclass
class WizardStep:
    workflow_key: str
    output_glob: str      # glob relative to project_root; step skipped if any match
    description: str


_STEPS = [
    WizardStep(
        workflow_key="create-prd",
        output_glob="_bmad-output/planning-artifacts/prd*.md",
        description="Create PRD — define what the product does",
    ),
    WizardStep(
        workflow_key="create-architecture",
        output_glob="_bmad-output/planning-artifacts/architecture*.md",
        description="Create Architecture — technical decisions & patterns",
    ),
    WizardStep(
        workflow_key="create-epics-and-stories",
        output_glob="_bmad-output/planning-artifacts/epic*.md",
        description="Create Epics & Stories — break PRD into stories",
    ),
    WizardStep(
        workflow_key="sprint-planning",
        output_glob="_bmad-output/implementation-artifacts/sprint-status.yaml",
        description="Sprint Planning — generate sprint-status.yaml",
    ),
]


def _step_done(project_root: Path, step: WizardStep) -> bool:
    return bool(list(project_root.glob(step.output_glob)))


def run_wizard_if_needed(project_root: Path) -> bool:
    """Run wizard steps as needed. Returns True when sprint-status.yaml exists."""
    missing = check_prerequisites()
    if missing:
        print(f"⚠  Missing prerequisites: {', '.join(missing)}")
        print("   Install GitHub Copilot CLI and `expect` (brew install expect) then retry.")
        return False

    # Build a minimal state stub for run_workflow
    state = ProjectState(
        epics=[],
        stories=[],
        project_root=project_root,
        sprint_status_path=project_root / "_bmad-output/implementation-artifacts/sprint-status.yaml",
    )

    print("\n🚀 BMAD New Project Wizard")
    print("   No sprint-status.yaml found — running setup sequence.\n")

    for i, step in enumerate(_STEPS, 1):
        if _step_done(project_root, step):
            print(f"   [{i}/4] ✅  {step.description} — already done, skipping")
            continue

        print(f"\n   [{i}/4] ▶  {step.description}")
        answer = input("      Run this step now? [Y/n] ").strip().lower()
        if answer == "n":
            print("      Skipped.")
            continue

        run_workflow(
            workflow_key=step.workflow_key,
            state=state,
            model=Model.SONNET,
        )

        if not _step_done(project_root, step):
            print(f"      ⚠  Expected output not found after step {i}.")
            answer = input("      Continue anyway? [y/N] ").strip().lower()
            if answer != "y":
                return False

    final = project_root / "_bmad-output/implementation-artifacts/sprint-status.yaml"
    return final.exists()
