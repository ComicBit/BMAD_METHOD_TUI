"""Tests for bmad_tui/wizard.py."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from bmad_tui.wizard import (
    _STEPS,
    WizardStep,
    _step_done,
    run_wizard_if_needed,
)
from bmad_tui.models import ProjectState


# ── Fixtures ──────────────────────────────────────────────────────────────

def _make_state(tmp_path: Path, stories=None, epics=None) -> ProjectState:
    return ProjectState(
        epics=epics or [],
        stories=stories or [],
        project_root=tmp_path,
        sprint_status_path=tmp_path / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml",
    )


# ── _step_done ────────────────────────────────────────────────────────────

class TestStepDone:
    def test_step_done_when_required_file_exists(self, tmp_path):
        (tmp_path / "prd.md").write_text("# PRD")
        step = WizardStep(
            workflow_key="create-prd",
            output_glob="prd.md",
            description="Write PRD",
        )
        assert _step_done(tmp_path, step) is True

    def test_step_not_done_when_file_missing(self, tmp_path):
        step = WizardStep(
            workflow_key="create-prd",
            output_glob="prd.md",
            description="Write PRD",
        )
        assert _step_done(tmp_path, step) is False

    def test_step_done_with_glob_pattern(self, tmp_path):
        docs = tmp_path / "_bmad-output" / "planning-artifacts"
        docs.mkdir(parents=True)
        (docs / "architecture.md").write_text("# Arch")
        step = WizardStep(
            workflow_key="create-architecture",
            output_glob="_bmad-output/planning-artifacts/architecture*.md",
            description="Design Architecture",
        )
        assert _step_done(tmp_path, step) is True

    def test_step_not_done_with_glob_no_match(self, tmp_path):
        step = WizardStep(
            workflow_key="create-architecture",
            output_glob="_bmad-output/planning-artifacts/architecture*.md",
            description="Design Architecture",
        )
        assert _step_done(tmp_path, step) is False

    def test_step_done_with_nested_glob(self, tmp_path):
        artifacts = tmp_path / "_bmad-output" / "planning-artifacts"
        artifacts.mkdir(parents=True)
        (artifacts / "epic-1-setup.md").write_text("# Story")
        step = WizardStep(
            workflow_key="create-epics-and-stories",
            output_glob="_bmad-output/planning-artifacts/epic*.md",
            description="Create Epics",
        )
        assert _step_done(tmp_path, step) is True

    def test_sprint_status_yaml_glob(self, tmp_path):
        impl = tmp_path / "_bmad-output" / "implementation-artifacts"
        impl.mkdir(parents=True)
        (impl / "sprint-status.yaml").write_text("development_status: {}")
        step = WizardStep(
            workflow_key="sprint-planning",
            output_glob="_bmad-output/implementation-artifacts/sprint-status.yaml",
            description="Sprint Planning",
        )
        assert _step_done(tmp_path, step) is True


# ── _STEPS definition ─────────────────────────────────────────────────────

class TestStepsDefinition:
    def test_steps_is_non_empty(self):
        assert len(_STEPS) > 0

    def test_all_steps_have_workflow_keys(self):
        for step in _STEPS:
            assert step.workflow_key, f"WizardStep missing workflow_key: {step}"

    def test_all_steps_have_descriptions(self):
        for step in _STEPS:
            assert step.description, f"WizardStep {step.workflow_key} missing description"

    def test_all_steps_have_output_glob(self):
        for step in _STEPS:
            assert step.output_glob, f"WizardStep {step.workflow_key} missing output_glob"

    def test_prd_step_exists(self):
        keys = [s.workflow_key for s in _STEPS]
        assert any("prd" in k for k in keys), "No PRD step found"

    def test_architecture_step_exists(self):
        keys = [s.workflow_key for s in _STEPS]
        assert any("architecture" in k for k in keys), "No architecture step found"

    def test_sprint_planning_is_last_step(self):
        # Sprint planning should come last (depends on epics/stories)
        assert "sprint-planning" in _STEPS[-1].workflow_key

    def test_prd_before_architecture(self):
        keys = [s.workflow_key for s in _STEPS]
        prd_idx = next(i for i, k in enumerate(keys) if "prd" in k)
        arch_idx = next(i for i, k in enumerate(keys) if "architecture" in k)
        assert prd_idx < arch_idx


# ── run_wizard_if_needed ──────────────────────────────────────────────────

class TestRunWizardIfNeeded:
    def test_returns_true_when_sprint_status_created(self, tmp_path):
        # Pre-create all step outputs (all steps done) → no interaction needed
        for step in _STEPS:
            # Resolve the glob to create a placeholder file
            glob = step.output_glob
            pattern = Path(glob)
            target = tmp_path / pattern.parent / (
                pattern.name.replace("*", "example")
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# placeholder")
        result = run_wizard_if_needed(tmp_path)
        assert result is True

    def test_returns_false_when_no_sprint_status_and_user_skips(self, tmp_path, monkeypatch):
        # Simulate user entering "n" for all prompts
        monkeypatch.setattr("builtins.input", lambda _: "n")
        result = run_wizard_if_needed(tmp_path)
        assert result is False

    def test_returns_false_when_prerequisites_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("bmad_tui.wizard.check_prerequisites", lambda: ["copilot", "expect"])
        result = run_wizard_if_needed(tmp_path)
        assert result is False


# ── WizardStep dataclass ──────────────────────────────────────────────────

class TestWizardStepDataclass:
    def test_can_instantiate_with_required_args(self):
        step = WizardStep(
            workflow_key="test-wf",
            output_glob="*.md",
            description="A test step",
        )
        assert step.workflow_key == "test-wf"
        assert step.output_glob == "*.md"
        assert step.description == "A test step"
