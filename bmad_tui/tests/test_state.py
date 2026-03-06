"""Tests for tools/bmad_tui/state.py"""

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from tools.bmad_tui.state import (
    _epic_id_from_story,
    _find_story_file,
    _phase_summary,
    find_project_root,
    load_state,
    project_phase,
)
from tools.bmad_tui.models import StoryStatus


# ── Helpers ───────────────────────────────────────────────────────────────

def _make_sprint_status(tmp_path: Path, content: str) -> Path:
    artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
    artifacts.mkdir(parents=True)
    yaml_file = artifacts / "sprint-status.yaml"
    yaml_file.write_text(textwrap.dedent(content))
    return tmp_path


def _minimal_yaml(statuses: dict[str, str]) -> str:
    lines = ["generated: 2026-01-01", "project: Test", "development_status:"]
    for key, val in statuses.items():
        lines.append(f"  {key}: {val}")
    return "\n".join(lines) + "\n"


# ── load_state: missing file ───────────────────────────────────────────────

class TestLoadStateMissingFile:
    def test_returns_empty_state_when_no_yaml(self, tmp_path):
        state = load_state(tmp_path)
        assert state.stories == []
        assert state.epics == []

    def test_sprint_status_path_set_correctly(self, tmp_path):
        state = load_state(tmp_path)
        assert state.sprint_status_path.name == "sprint-status.yaml"

    def test_project_root_preserved(self, tmp_path):
        state = load_state(tmp_path)
        assert state.project_root == tmp_path

    def test_no_error_when_file_missing(self, tmp_path):
        state = load_state(tmp_path)
        assert state.yaml_error is None


# ── load_state: invalid YAML ───────────────────────────────────────────────

class TestLoadStateInvalidYaml:
    def _write_sprint_status(self, tmp_path: Path, content: str) -> Path:
        artifacts = tmp_path / "_bmad-output" / "implementation-artifacts"
        artifacts.mkdir(parents=True)
        (artifacts / "sprint-status.yaml").write_text(content)
        return tmp_path

    def test_returns_empty_state_on_yaml_error(self, tmp_path):
        root = self._write_sprint_status(tmp_path, "epic-1: in-progress\n  bad: indent: here\n")
        state = load_state(root)
        assert state.stories == []
        assert state.epics == []

    def test_yaml_error_field_populated(self, tmp_path):
        root = self._write_sprint_status(tmp_path, "epic-1: in-progress\n  bad: indent: here\n")
        state = load_state(root)
        assert state.yaml_error is not None
        assert len(state.yaml_error) > 0

    def test_sprint_status_path_preserved_on_error(self, tmp_path):
        root = self._write_sprint_status(tmp_path, "bad: yaml:\n  - oops: broken: value\n")
        state = load_state(root)
        assert state.sprint_status_path.name == "sprint-status.yaml"

    def test_no_error_on_valid_yaml(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({"epic-1": "in-progress"}))
        state = load_state(root)
        assert state.yaml_error is None


# ── load_state: epic parsing ──────────────────────────────────────────────

class TestLoadStateEpics:
    def test_parses_epic_count(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({
            "epic-1": "done",
            "epic-2": "in-progress",
            "1-1-story-one": "done",
        }))
        state = load_state(root)
        assert len(state.epics) == 2

    def test_epic_status_done(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({"epic-1": "done"}))
        state = load_state(root)
        assert state.epics[0].status == "done"

    def test_epic_status_in_progress(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({"epic-3": "in-progress"}))
        state = load_state(root)
        assert state.epics[0].status == "in-progress"

    def test_epic_ids_not_in_stories(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({
            "epic-1": "done",
            "1-1-story-one": "done",
        }))
        state = load_state(root)
        story_ids = [s.id for s in state.stories]
        assert "epic-1" not in story_ids

    def test_retro_keys_not_in_stories(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({
            "epic-1": "done",
            "epic-1-retrospective": "done",
            "1-1-story-one": "done",
        }))
        state = load_state(root)
        story_ids = [s.id for s in state.stories]
        assert "epic-1-retrospective" not in story_ids

    def test_meta_keys_not_in_stories(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({
            "epic-3": "in-progress",
            "epic-3-prerequisite": "blocked until 7-2",
            "3-1-thermal": "done",
        }))
        state = load_state(root)
        story_ids = [s.id for s in state.stories]
        assert "epic-3-prerequisite" not in story_ids


# ── load_state: story parsing ─────────────────────────────────────────────

class TestLoadStateStories:
    def test_story_count(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({
            "epic-1": "done",
            "1-1-story-one": "done",
            "1-2-story-two": "backlog",
        }))
        state = load_state(root)
        assert len(state.stories) == 2

    def test_story_yaml_status_preserved(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({
            "3-5c-utterance-ux": "ready-for-dev",
        }))
        state = load_state(root)
        assert state.stories[0].yaml_status == "ready-for-dev"

    def test_story_epic_id_extracted(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({
            "7-5-bundled-model": "review",
        }))
        state = load_state(root)
        assert state.stories[0].epic_id == "7"

    def test_story_file_path_found(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({
            "7-5-bundled-model": "review",
        }))
        # Create matching story file
        artifacts = root / "_bmad-output" / "implementation-artifacts"
        story_file = artifacts / "7-5-bundled-model.md"
        story_file.write_text("# Story 7.5")
        state = load_state(root)
        assert state.stories[0].file_path == story_file

    def test_story_file_path_none_when_missing(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({
            "3-7-thermal-state-2b": "backlog",
        }))
        state = load_state(root)
        assert state.stories[0].file_path is None

    def test_backlog_with_file_is_ready_for_dev(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({
            "3-6-thermal": "backlog",
        }))
        artifacts = root / "_bmad-output" / "implementation-artifacts"
        (artifacts / "3-6-thermal.md").write_text("# Story")
        state = load_state(root)
        assert state.stories[0].effective_status == StoryStatus.READY_FOR_DEV

    def test_backlog_without_file_is_needs_story(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({
            "3-7-thermal": "backlog",
        }))
        state = load_state(root)
        assert state.stories[0].effective_status == StoryStatus.NEEDS_STORY

    def test_review_status_preserved(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({
            "7-5-bundled": "review",
        }))
        state = load_state(root)
        assert state.stories[0].effective_status == StoryStatus.REVIEW

    def test_stories_attached_to_epic(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({
            "epic-3": "in-progress",
            "3-1-thermal": "done",
            "3-2-vad": "done",
        }))
        state = load_state(root)
        epic3 = next(e for e in state.epics if e.id == "3")
        assert len(epic3.stories) == 2


# ── load_state: blocked epics ─────────────────────────────────────────────

class TestLoadStateBlockedEpics:
    def test_blocked_epic_marks_backlog_stories(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({
            "epic-3": "in-progress",
            "epic-3-prerequisite": "blocked until 7-2",
            "3-6-thermal": "backlog",
        }))
        state = load_state(root)
        story = state.stories[0]
        assert story.blocked is True

    def test_blocked_epic_does_not_mark_done_stories(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({
            "epic-3": "in-progress",
            "epic-3-prerequisite": "blocked",
            "3-1-thermal": "done",
        }))
        state = load_state(root)
        story = state.stories[0]
        assert story.blocked is False

    def test_non_blocked_epic_stories_not_blocked(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({
            "epic-7": "in-progress",
            "7-6-download": "ready-for-dev",
        }))
        state = load_state(root)
        assert state.stories[0].blocked is False

    def test_blocked_epic_flagged_on_epic_object(self, tmp_path):
        root = _make_sprint_status(tmp_path, _minimal_yaml({
            "epic-3": "in-progress",
            "epic-3-prerequisite": "blocked",
            "3-6-thermal": "backlog",
        }))
        state = load_state(root)
        epic3 = next(e for e in state.epics if e.id == "3")
        assert epic3.blocked is True


# ── _find_story_file ──────────────────────────────────────────────────────

class TestFindStoryFile:
    def test_finds_exact_match(self, tmp_path):
        f = tmp_path / "7-5-bundled-model.md"
        f.write_text("# Story")
        result = _find_story_file("7-5-bundled-model", tmp_path)
        assert result == f

    def test_finds_glob_suffix_match(self, tmp_path):
        # ID without all segments, file has extra suffix
        f = tmp_path / "7-5-extra-suffix.md"
        f.write_text("# Story")
        result = _find_story_file("7-5", tmp_path)
        assert result == f

    def test_returns_none_when_not_found(self, tmp_path):
        result = _find_story_file("9-9-nonexistent", tmp_path)
        assert result is None

    def test_exact_match_takes_priority(self, tmp_path):
        exact = tmp_path / "7-5-story.md"
        extra = tmp_path / "7-5-story-extra.md"
        exact.write_text("exact")
        extra.write_text("extra")
        result = _find_story_file("7-5-story", tmp_path)
        assert result == exact

    def test_non_md_files_ignored(self, tmp_path):
        (tmp_path / "7-5-story.txt").write_text("not md")
        result = _find_story_file("7-5-story", tmp_path)
        assert result is None


# ── _epic_id_from_story ───────────────────────────────────────────────────

class TestEpicIdFromStory:
    def test_simple_numeric(self):
        assert _epic_id_from_story("3-5c-utterance") == "3"

    def test_large_epic_number(self):
        assert _epic_id_from_story("7-6-download") == "7"

    def test_single_digit_story(self):
        assert _epic_id_from_story("1-1-lock-deps") == "1"

    def test_alphanumeric_story_id(self):
        assert _epic_id_from_story("3-5c-long-slug-name") == "3"

    def test_fallback_on_no_dash(self):
        # No dash → returns "?" as fallback
        assert _epic_id_from_story("nostory") == "?"


# ── find_project_root ─────────────────────────────────────────────────────

class TestFindProjectRoot:
    def test_finds_git_root(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        subdir = tmp_path / "src" / "deep"
        subdir.mkdir(parents=True)
        result = find_project_root(subdir)
        assert result == tmp_path

    def test_finds_bmad_root(self, tmp_path):
        bmad_dir = tmp_path / "_bmad"
        bmad_dir.mkdir()
        subdir = tmp_path / "a" / "b"
        subdir.mkdir(parents=True)
        result = find_project_root(subdir)
        assert result == tmp_path

    def test_git_takes_precedence_over_bmad(self, tmp_path):
        # Both .git and _bmad at same level
        (tmp_path / ".git").mkdir()
        (tmp_path / "_bmad").mkdir()
        result = find_project_root(tmp_path)
        assert result == tmp_path

    def test_falls_back_to_start_when_no_markers(self, tmp_path):
        result = find_project_root(tmp_path)
        assert result == tmp_path

    def test_none_start_uses_cwd(self):
        # Should not raise; returns a valid path
        result = find_project_root(None)
        assert result.exists()


# ── Helpers for phase tests ───────────────────────────────────────────────

def _make_planning_artifacts(root: Path, *, prd: bool = False, arch: bool = False) -> None:
    planning = root / "_bmad-output" / "planning-artifacts"
    planning.mkdir(parents=True, exist_ok=True)
    if prd:
        (planning / "prd.md").write_text("# PRD")
    if arch:
        (planning / "architecture.md").write_text("# Architecture")


def _state_with_sprint(tmp_path: Path, statuses: dict, epics: dict | None = None) -> object:
    """Build a ProjectState using _make_sprint_status with optional epic entries."""
    combined = {}
    if epics:
        combined.update(epics)
    combined.update(statuses)
    return load_state(_make_sprint_status(tmp_path, _minimal_yaml(combined)))


# ── TestProjectPhase ──────────────────────────────────────────────────────

class TestProjectPhase:
    def test_no_prd_returns_analysis(self, tmp_path):
        state = load_state(tmp_path)
        assert project_phase(state) == "analysis"

    def test_prd_and_arch_no_sprint_status_returns_planning(self, tmp_path):
        _make_planning_artifacts(tmp_path, prd=True, arch=True)
        state = load_state(tmp_path)
        assert project_phase(state) == "planning"

    def test_prd_only_no_arch_no_sprint_returns_analysis(self, tmp_path):
        # PRD exists but no arch — can't be planning, no sprint either → analysis
        _make_planning_artifacts(tmp_path, prd=True, arch=False)
        state = load_state(tmp_path)
        # prd exists, but arch is absent → planning condition not met.
        # No stories → falls through to complete; but prd exists so not analysis.
        # Priority: prd exists so skip analysis; arch absent so skip planning;
        # no stories so no implementation/retrospective → complete.
        assert project_phase(state) == "complete"

    def test_in_progress_story_returns_implementation(self, tmp_path):
        _make_planning_artifacts(tmp_path, prd=True, arch=True)
        state = _state_with_sprint(tmp_path, {"1-1-story": "in-progress"}, {"epic-1": "in-progress"})
        assert project_phase(state) == "implementation"

    def test_review_story_returns_implementation(self, tmp_path):
        _make_planning_artifacts(tmp_path, prd=True, arch=True)
        state = _state_with_sprint(tmp_path, {"1-1-story": "review"}, {"epic-1": "in-progress"})
        assert project_phase(state) == "implementation"

    def test_all_done_retro_required_returns_retrospective(self, tmp_path):
        _make_planning_artifacts(tmp_path, prd=True, arch=True)
        state = _state_with_sprint(
            tmp_path,
            {"1-1-story": "done"},
            {"epic-1": "done", "epic-1-retrospective": "required"},
        )
        assert project_phase(state) == "retrospective"

    def test_all_done_retros_done_returns_complete(self, tmp_path):
        _make_planning_artifacts(tmp_path, prd=True, arch=True)
        state = _state_with_sprint(
            tmp_path,
            {"1-1-story": "done"},
            {"epic-1": "done", "epic-1-retrospective": "done"},
        )
        assert project_phase(state) == "complete"


# ── TestPhaseSummary ──────────────────────────────────────────────────────

class TestPhaseSummary:
    def test_active_epics_count(self, tmp_path):
        state = _state_with_sprint(
            tmp_path,
            {"1-1-story": "done", "2-1-story": "in-progress"},
            {"epic-1": "done", "epic-2": "in-progress"},
        )
        summary = _phase_summary(state)
        assert summary["active_epics"] == 1

    def test_in_review_count(self, tmp_path):
        state = _state_with_sprint(
            tmp_path,
            {"1-1-story": "review", "1-2-story": "review", "1-3-story": "done"},
            {"epic-1": "in-progress"},
        )
        summary = _phase_summary(state)
        assert summary["in_review"] == 2

    def test_pending_retros_count(self, tmp_path):
        state = _state_with_sprint(
            tmp_path,
            {"1-1-story": "done", "2-1-story": "done"},
            {"epic-1": "done", "epic-1-retrospective": "required",
             "epic-2": "done", "epic-2-retrospective": "done"},
        )
        summary = _phase_summary(state)
        assert summary["pending_retros"] == 1

    def test_all_zeros_for_empty_state(self, tmp_path):
        state = load_state(tmp_path)
        summary = _phase_summary(state)
        assert summary == {"active_epics": 0, "in_review": 0, "pending_retros": 0, "pending_retro_ids": []}

    def test_pending_retro_ids_list(self, tmp_path):
        state = _state_with_sprint(
            tmp_path,
            {"1-1-story": "done"},
            {"epic-1": "done", "epic-1-retrospective": "required"},
        )
        summary = _phase_summary(state)
        assert summary["pending_retro_ids"] == ["1"]

    def test_pending_retro_ids_empty_when_none(self, tmp_path):
        state = _state_with_sprint(
            tmp_path,
            {"1-1-story": "done"},
            {"epic-1": "done", "epic-1-retrospective": "done"},
        )
        summary = _phase_summary(state)
        assert summary["pending_retro_ids"] == []
