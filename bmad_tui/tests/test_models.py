"""Tests for tools/bmad_tui/models.py"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from tools.bmad_tui.models import (
    Epic,
    Model,
    ProjectState,
    STATUS_BADGES,
    Story,
    StoryStatus,
    WorkflowDef,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

def _story(id: str, yaml_status: str, file_path: Path | None = None, blocked: bool = False) -> Story:
    return Story(id=id, yaml_status=yaml_status, epic_id=id.split("-")[0], file_path=file_path, blocked=blocked)


# ── StoryStatus.effective_status ──────────────────────────────────────────

class TestEffectiveStatus:
    def test_backlog_with_file_is_ready_for_dev(self, tmp_path):
        f = tmp_path / "3-5c-utterance-ux.md"
        f.touch()
        s = _story("3-5c-utterance-ux", "backlog", file_path=f)
        assert s.effective_status == StoryStatus.READY_FOR_DEV

    def test_backlog_without_file_is_needs_story(self):
        s = _story("3-6-thermal-downgrade", "backlog", file_path=None)
        assert s.effective_status == StoryStatus.NEEDS_STORY

    def test_ready_for_dev(self, tmp_path):
        f = tmp_path / "story.md"
        f.touch()
        s = _story("3-5c-utterance", "ready-for-dev", file_path=f)
        assert s.effective_status == StoryStatus.READY_FOR_DEV

    def test_in_progress(self):
        s = _story("3-5c-utterance", "in-progress")
        assert s.effective_status == StoryStatus.IN_PROGRESS

    def test_review(self):
        s = _story("7-5-bootstrap", "review")
        assert s.effective_status == StoryStatus.REVIEW

    def test_done(self):
        s = _story("1-1-lock-deps", "done")
        assert s.effective_status == StoryStatus.DONE

    def test_blocked(self):
        s = _story("4-1-diarizer", "blocked")
        assert s.effective_status == StoryStatus.BLOCKED

    def test_unknown_yaml_value(self):
        s = _story("9-9-future", "some-future-status")
        assert s.effective_status == StoryStatus.UNKNOWN

    def test_backlog_with_file_is_not_needs_story(self, tmp_path):
        f = tmp_path / "file.md"
        f.touch()
        s = _story("5-1-refinement", "backlog", file_path=f)
        assert s.effective_status != StoryStatus.NEEDS_STORY

    def test_done_regardless_of_file(self, tmp_path):
        f = tmp_path / "story.md"
        f.touch()
        s = _story("1-1-lock", "done", file_path=f)
        assert s.effective_status == StoryStatus.DONE


# ── Story.short_id ────────────────────────────────────────────────────────

class TestShortId:
    def test_standard_two_segment(self):
        s = _story("7-5-bundled-model", "backlog")
        assert s.short_id == "7-5"

    def test_alphanumeric_segment(self):
        s = _story("3-5c-utterance-streaming-ux", "backlog")
        assert s.short_id == "3-5c"

    def test_single_epic_segment(self):
        s = _story("3-only", "backlog")
        assert s.short_id == "3-only"

    def test_minimal_id(self):
        s = _story("1-1", "done")
        assert s.short_id == "1-1"

    def test_long_slug_only_first_two(self):
        s = _story("7-6-download-manager-ui", "ready-for-dev")
        assert s.short_id == "7-6"


# ── Story.title ───────────────────────────────────────────────────────────

class TestTitle:
    def test_derives_title_from_id(self):
        s = _story("7-5-bundled-model-bootstrap", "backlog")
        assert s.title == "Bundled Model Bootstrap"

    def test_multiword_title(self):
        s = _story("3-5c-utterance-streaming-ux-live-partial", "backlog")
        assert s.title == "Utterance Streaming Ux Live Partial"

    def test_single_word_after_id(self):
        s = _story("7-6-download", "backlog")
        assert s.title == "Download"

    def test_no_title_segments_falls_back_to_id(self):
        s = _story("1-1", "done")
        # Only two segments — title falls back to id
        assert s.title == "1-1"

    def test_capitalises_each_word(self):
        s = _story("4-2-fusion-service", "ready-for-dev")
        assert s.title == "Fusion Service"


# ── Story.primary_workflow ────────────────────────────────────────────────

class TestPrimaryWorkflow:
    def test_needs_story_creates_story(self):
        s = _story("3-7-thermal", "backlog", file_path=None)
        assert s.primary_workflow == "create-story"

    def test_ready_for_dev_runs_dev_story(self, tmp_path):
        f = tmp_path / "s.md"; f.touch()
        s = _story("3-5c-ux", "ready-for-dev", file_path=f)
        assert s.primary_workflow == "dev-story"

    def test_in_progress_runs_dev_story(self):
        s = _story("3-5c-ux", "in-progress")
        assert s.primary_workflow == "dev-story"

    def test_review_runs_code_review(self):
        s = _story("7-5-bootstrap", "review")
        assert s.primary_workflow == "code-review"

    def test_done_has_no_primary_workflow(self):
        s = _story("1-1-lock", "done")
        assert s.primary_workflow is None

    def test_blocked_has_no_primary_workflow(self):
        s = _story("4-1-diarizer", "blocked")
        assert s.primary_workflow is None

    def test_backlog_with_file_runs_dev_story(self, tmp_path):
        f = tmp_path / "s.md"; f.touch()
        s = _story("3-6-thermal", "backlog", file_path=f)
        assert s.primary_workflow == "dev-story"


# ── Model enum ────────────────────────────────────────────────────────────

class TestModel:
    def test_sonnet_value(self):
        assert Model.SONNET.value == "claude-sonnet-4.6"

    def test_opus_value(self):
        assert Model.OPUS.value == "claude-opus-4.6"

    def test_codex_value(self):
        assert Model.CODEX.value == "gpt-5.3-codex"

    def test_labels_are_short(self):
        for m in Model:
            assert len(m.label()) < 20

    def test_all_models_have_labels(self):
        for m in Model:
            assert m.label()


# ── StoryStatus metadata ──────────────────────────────────────────────────

_CANONICAL_SYMBOLS = {"○", "●", "◆", "◈", "✓", "·", "⊘", "?"}

class TestStoryStatusMetadata:
    def test_all_statuses_have_symbol(self):
        for s in StoryStatus:
            assert s.emoji in _CANONICAL_SYMBOLS, f"{s} symbol '{s.emoji}' not in canonical set"

    def test_per_status_symbols(self):
        assert StoryStatus.NEEDS_STORY.emoji == "○"
        assert StoryStatus.READY_FOR_DEV.emoji == "●"
        assert StoryStatus.IN_PROGRESS.emoji == "◆"
        assert StoryStatus.REVIEW.emoji == "◈"
        assert StoryStatus.DONE.emoji == "✓"
        assert StoryStatus.BACKLOG.emoji == "·"
        assert StoryStatus.BLOCKED.emoji == "⊘"
        assert StoryStatus.UNKNOWN.emoji == "?"

    def test_all_statuses_have_badge_label(self):
        for s in StoryStatus:
            assert s.badge_label


# ── Epic ──────────────────────────────────────────────────────────────────

class TestEpic:
    def test_done_progress_icon(self):
        e = Epic(id="1", status="done")
        assert e.progress_icon == "✓"

    def test_in_progress_icon(self):
        e = Epic(id="3", status="in-progress")
        assert e.progress_icon == "→"

    def test_backlog_icon(self):
        e = Epic(id="5", status="backlog")
        assert e.progress_icon == "○"

    def test_done_rich_style(self):
        e = Epic(id="1", status="done")
        assert "#50fa7b" in e.rich_style or "green" in e.rich_style

    def test_in_progress_rich_style(self):
        e = Epic(id="3", status="in-progress")
        assert "#8be9fd" in e.rich_style or "blue" in e.rich_style


# ── ProjectState.actionable_stories ──────────────────────────────────────

class TestProjectStateActionable:
    def _make_state(self, stories: list[Story]) -> ProjectState:
        return ProjectState(
            epics=[],
            stories=stories,
            project_root=Path("/tmp/fake"),
            sprint_status_path=Path("/tmp/fake/sprint-status.yaml"),
        )

    def test_review_before_ready_for_dev(self, tmp_path):
        f = tmp_path / "s.md"; f.touch()
        review = _story("7-5-bootstrap", "review")
        ready = _story("3-5c-ux", "ready-for-dev", file_path=f)
        state = self._make_state([ready, review])
        result = state.actionable_stories()
        assert result[0].effective_status == StoryStatus.REVIEW

    def test_in_progress_before_ready_for_dev(self, tmp_path):
        f = tmp_path / "s.md"; f.touch()
        in_prog = _story("3-5c-ux", "in-progress")
        ready = _story("7-6-dl", "ready-for-dev", file_path=f)
        state = self._make_state([ready, in_prog])
        result = state.actionable_stories()
        assert result[0].effective_status == StoryStatus.IN_PROGRESS

    def test_done_stories_last(self, tmp_path):
        f = tmp_path / "s.md"; f.touch()
        done = _story("1-1-lock", "done")
        ready = _story("3-5c-ux", "ready-for-dev", file_path=f)
        state = self._make_state([done, ready])
        result = state.actionable_stories()
        assert result[-1].effective_status == StoryStatus.DONE

    def test_needs_story_before_done(self):
        needs = _story("3-7-thermal", "backlog", file_path=None)
        done = _story("1-1-lock", "done")
        state = self._make_state([done, needs])
        result = state.actionable_stories()
        assert result[0].effective_status == StoryStatus.NEEDS_STORY

    def test_empty_state_returns_empty_list(self):
        state = self._make_state([])
        assert state.actionable_stories() == []


# ── TestStatusBadges ──────────────────────────────────────────────────────────

class TestStatusBadges:
    def test_all_primary_statuses_have_badge(self):
        for status in StoryStatus:
            assert status in STATUS_BADGES, f"{status} missing from STATUS_BADGES"

    def test_badge_keys_match_story_status_enum(self):
        assert set(STATUS_BADGES.keys()) == set(StoryStatus)

    def test_needs_story_is_red(self):
        badge = STATUS_BADGES[StoryStatus.NEEDS_STORY]
        assert "#ff6b6b" in badge or "red" in badge

    def test_blocked_has_red_background(self):
        badge = STATUS_BADGES[StoryStatus.BLOCKED]
        assert "#ff5555" in badge or "red" in badge

    def test_done_is_dim(self):
        badge = STATUS_BADGES[StoryStatus.DONE]
        assert "#6272a4" in badge or "dim" in badge
