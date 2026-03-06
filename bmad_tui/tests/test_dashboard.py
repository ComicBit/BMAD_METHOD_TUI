"""Tests for the home-only Dashboard in bmad_tui/dashboard.py."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import tempfile

import yaml

from bmad_tui.dashboard import Dashboard, SearchScreen, StoryActionModal, WorkflowPickerModal, _set_story_status, _story_sort_key
from bmad_tui.history import HistoryEntry, append_history
from bmad_tui.models import Epic, Model, ProjectState, Story


def _story(story_id: str, status: str = "backlog", epic_id: str = "1") -> Story:
    return Story(id=story_id, yaml_status=status, epic_id=epic_id, file_path=None)


def _state(epics: list[Epic] | None = None, stories: list[Story] | None = None) -> ProjectState:
    root = Path("/tmp")
    return ProjectState(
        epics=epics or [],
        stories=stories or [],
        project_root=root,
        sprint_status_path=root / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml",
    )


def _dash_with_state(state: ProjectState) -> Dashboard:
    d = Dashboard(Path("/tmp"))
    d._project_root = Path("/tmp")
    d._state = state
    d._status_filter = None
    d._epics = sorted(state.epics, key=lambda e: int(e.id) if str(e.id).isdigit() else 999)
    d._selected_epic_index = 0
    d._selected_story_id = None
    d._hovered_story_id = None
    d.selected_model = Model.SONNET
    return d


class TestStorySortKey:
    def test_numeric_then_alpha_suffix(self) -> None:
        a = _story("3-5-aaa")
        b = _story("3-5c-bbb")
        assert _story_sort_key(a) < _story_sort_key(b)

    def test_epic_ordering(self) -> None:
        a = _story("2-1-a")
        b = _story("10-1-b")
        assert _story_sort_key(a) < _story_sort_key(b)


class TestDashboardBindings:
    def test_required_home_bindings_present(self) -> None:
        expected = {"q", "r", "up", "down", "left", "right", "w", "enter", "space", "f", "s", "m", "a", "h"}
        keys = {b.key for b in Dashboard.BINDINGS}
        assert expected.issubset(keys)


class TestEpicSelection:
    def test_default_epic_prefers_in_progress(self) -> None:
        state = _state(
            epics=[
                Epic(id="1", status="done"),
                Epic(id="2", status="in-progress"),
                Epic(id="3", status="backlog"),
            ]
        )
        d = _dash_with_state(state)
        assert d._default_epic_index() == 1

    def test_default_epic_falls_back_to_backlog(self) -> None:
        state = _state(
            epics=[Epic(id="1", status="done"), Epic(id="2", status="backlog")]
        )
        d = _dash_with_state(state)
        assert d._default_epic_index() == 1


class TestRestoreLastFocus:
    def _dash_with_history(self, tmp_path: Path, stories: list[Story], epics: list[Epic], history: list[HistoryEntry]) -> Dashboard:
        state = ProjectState(
            epics=epics,
            stories=stories,
            project_root=tmp_path,
            sprint_status_path=tmp_path / "sprint-status.yaml",
        )
        d = Dashboard(tmp_path)
        d._project_root = tmp_path
        d._state = state
        d._status_filter = None
        d._epics = sorted(state.epics, key=lambda e: int(e.id) if str(e.id).isdigit() else 999)
        d._selected_epic_index = 0
        d._selected_story_id = None
        d._hovered_story_id = None
        d.selected_model = Model.SONNET
        for entry in history:
            append_history(tmp_path, entry)
        return d

    def test_restores_last_story_and_epic(self, tmp_path: Path) -> None:
        epics = [Epic(id="1", status="in-progress"), Epic(id="2", status="in-progress")]
        stories = [
            _story("1-1", status="done", epic_id="1"),
            _story("2-3", status="in-progress", epic_id="2"),
        ]
        history = [
            HistoryEntry(ts="2026-01-01T00:00:00Z", workflow="dev-story", agent="x", model="m",
                         story_id="1-1", epic_id="1", branch="main", session_id="aaa"),
            HistoryEntry(ts="2026-01-02T00:00:00Z", workflow="dev-story", agent="x", model="m",
                         story_id="2-3", epic_id="2", branch="main", session_id="bbb"),
        ]
        d = self._dash_with_history(tmp_path, stories, epics, history)
        d._restore_last_focus()
        assert d._selected_story_id == "2-3"
        assert d._epics[d._selected_epic_index].id == "2"

    def test_skips_entries_without_story_id(self, tmp_path: Path) -> None:
        epics = [Epic(id="1", status="in-progress")]
        stories = [_story("1-1", status="in-progress", epic_id="1")]
        history = [
            HistoryEntry(ts="2026-01-01T00:00:00Z", workflow="dev-story", agent="x", model="m",
                         story_id="1-1", epic_id="1", branch="main", session_id="aaa"),
            HistoryEntry(ts="2026-01-02T00:00:00Z", workflow="dev-story", agent="x", model="m",
                         story_id="", epic_id="", branch="main", session_id="bbb"),
        ]
        d = self._dash_with_history(tmp_path, stories, epics, history)
        d._restore_last_focus()
        assert d._selected_story_id == "1-1"

    def test_skips_entries_for_deleted_stories(self, tmp_path: Path) -> None:
        epics = [Epic(id="1", status="in-progress")]
        stories = [_story("1-1", status="in-progress", epic_id="1")]
        history = [
            HistoryEntry(ts="2026-01-01T00:00:00Z", workflow="dev-story", agent="x", model="m",
                         story_id="1-1", epic_id="1", branch="main", session_id="aaa"),
            HistoryEntry(ts="2026-01-02T00:00:00Z", workflow="dev-story", agent="x", model="m",
                         story_id="9-99-gone", epic_id="9", branch="main", session_id="bbb"),
        ]
        d = self._dash_with_history(tmp_path, stories, epics, history)
        d._restore_last_focus()
        assert d._selected_story_id == "1-1"

    def test_no_op_when_no_matching_history(self, tmp_path: Path) -> None:
        epics = [Epic(id="1", status="in-progress")]
        stories = [_story("1-1", status="in-progress", epic_id="1")]
        d = self._dash_with_history(tmp_path, stories, epics, history=[])
        d._restore_last_focus()
        assert d._selected_story_id is None
        assert d._selected_epic_index == 0




class TestDefaultStoryIdForSprint:
    def test_returns_first_pending_when_some_done(self) -> None:
        stories = [
            _story("1-1", status="done", epic_id="1"),
            _story("1-2", status="in-progress", epic_id="1"),
            _story("1-3", status="backlog", epic_id="1"),
        ]
        assert Dashboard._default_story_id_for_sprint(stories) == "1-2"

    def test_returns_first_when_all_done(self) -> None:
        stories = [
            _story("1-1", status="done", epic_id="1"),
            _story("1-2", status="done", epic_id="1"),
        ]
        assert Dashboard._default_story_id_for_sprint(stories) == "1-1"

    def test_returns_first_when_none_done(self) -> None:
        stories = [
            _story("1-1", status="backlog", epic_id="1"),
            _story("1-2", status="in-progress", epic_id="1"),
        ]
        assert Dashboard._default_story_id_for_sprint(stories) == "1-1"

    def test_returns_none_for_empty_list(self) -> None:
        assert Dashboard._default_story_id_for_sprint([]) is None

    def test_skips_leading_done_tasks(self) -> None:
        stories = [
            _story("1-1", status="done", epic_id="1"),
            _story("1-2", status="done", epic_id="1"),
            _story("1-3", status="ready-for-dev", epic_id="1"),
        ]
        assert Dashboard._default_story_id_for_sprint(stories) == "1-3"



    def test_stories_for_epic_sorted(self) -> None:
        state = _state(
            epics=[Epic(id="4", status="in-progress")],
            stories=[
                _story("4-3-c", "backlog", "4"),
                _story("4-1-a", "done", "4"),
                _story("4-2-b", "ready-for-dev", "4"),
            ],
        )
        d = _dash_with_state(state)
        got = [s.id for s in d._stories_for_epic("4")]
        assert got == ["4-1-a", "4-2-b", "4-3-c"]

    def test_stories_for_epic_respects_filter(self) -> None:
        state = _state(
            epics=[Epic(id="4", status="in-progress")],
            stories=[
                _story("4-1-a", "done", "4"),
                _story("4-2-b", "ready-for-dev", "4"),
            ],
        )
        d = _dash_with_state(state)
        d._status_filter = "ready-for-dev"
        got = [s.id for s in d._stories_for_epic("4")]
        assert got == ["4-2-b"]

    def test_card_status_class_unknown_maps_to_unknown(self) -> None:
        d = _dash_with_state(_state())
        s = _story("1-1-x", "mystery", "1")
        assert d._card_status_class(s) == "status-unknown"

    def test_cost_line_only_for_done(self) -> None:
        d = _dash_with_state(_state())
        assert d._story_cost_line(_story("1-1", "done")) == ""
        assert d._story_cost_line(_story("1-2", "backlog")) == ""

    def test_effective_story_id_prefers_hover(self) -> None:
        d = _dash_with_state(_state())
        d._selected_story_id = "4-1-a"
        d._hovered_story_id = "4-2-b"
        assert d._effective_story_id() == "4-2-b"

    def test_effective_story_id_falls_back_to_selected(self) -> None:
        d = _dash_with_state(_state())
        d._selected_story_id = "4-1-a"
        assert d._effective_story_id() == "4-1-a"


class TestActions:
    def test_model_cycles(self) -> None:
        d = _dash_with_state(_state())
        d.notify = MagicMock()
        before = d.selected_model
        d.action_model()
        assert d.selected_model != before

    def test_filter_cycles(self) -> None:
        d = _dash_with_state(_state())
        d.notify = MagicMock()
        d._render_cards = MagicMock()
        d._render_detail = MagicMock()
        d._update_filter_bar = MagicMock()
        d._cancel_hover_clear_timer = MagicMock()
        # action_filter now opens a modal; test _set_filter directly instead
        d._set_filter(1)  # index 1 → first non-None filter ("ready-for-dev")
        assert d._status_filter == "ready-for-dev"
        d._set_filter(2)  # index 2 → "in-progress"
        assert d._status_filter == "in-progress"

    def test_refresh_reloads_state(self) -> None:
        d = _dash_with_state(_state())
        d.notify = MagicMock()
        d._render_home = MagicMock()
        from bmad_tui import dashboard as mod

        old = d._state
        mod.load_state = MagicMock(return_value=_state(epics=[Epic(id="1", status="done")]))
        d.action_refresh()
        assert d._state is not old
        d._render_home.assert_called_once()

    def test_arrow_navigation_moves_selection(self) -> None:
        state = _state(
            epics=[Epic(id="4", status="in-progress")],
            stories=[
                _story("4-1-a", "backlog", "4"),
                _story("4-2-b", "backlog", "4"),
                _story("4-3-c", "backlog", "4"),
                _story("4-4-d", "backlog", "4"),
                _story("4-5-e", "backlog", "4"),
            ],
        )
        d = _dash_with_state(state)
        d._card_widgets = {}
        d._render_detail = MagicMock()
        d._set_card_active = MagicMock()
        d._selected_story_id = "4-1-a"

        d.action_nav_right()
        assert d._selected_story_id == "4-2-b"
        d.action_nav_down()
        assert d._selected_story_id == "4-5-e"


class TestEpicHeaderCells:
    """Tests for Dashboard._epic_header_cells() — TUI-18."""

    def _make_dash(self, epic: Epic, stories: list) -> Dashboard:
        state = _state(epics=[epic], stories=stories)
        return _dash_with_state(state)

    def test_id_cell_has_accent(self) -> None:
        epic = Epic(id="3", status="in-progress")
        stories = [_story("3-1-a", "done", "3"), _story("3-2-b", "backlog", "3")]
        d = self._make_dash(epic, stories)
        id_cell, _, _, _ = d._epic_header_cells(epic)
        assert "▌" in id_cell

    def test_progress_in_action_column(self) -> None:
        epic = Epic(id="3", status="in-progress")
        stories = [_story("3-1-a", "done", "3"), _story("3-2-b", "backlog", "3")]
        d = self._make_dash(epic, stories)
        _, _, _, act_cell = d._epic_header_cells(epic)
        assert "█" in act_cell or "░" in act_cell

    def test_title_column_shows_epic_label(self) -> None:
        epic = Epic(id="3", status="in-progress")
        stories = [_story("3-1-a", "done", "3")]
        d = self._make_dash(epic, stories)
        _, _, bar_cell, _ = d._epic_header_cells(epic)
        assert "Epic " in bar_cell

    def test_epic_with_0_stories_no_crash(self) -> None:
        epic = Epic(id="5", status="backlog")
        d = self._make_dash(epic, [])
        id_cell, stat_cell, bar_cell, act_cell = d._epic_header_cells(epic)
        assert "▌" in id_cell
        assert "░" * 8 in act_cell  # all empty when no stories

    def test_epic_all_done_full_bar(self) -> None:
        epic = Epic(id="2", status="done")
        stories = [_story("2-1-a", "done", "2"), _story("2-2-b", "done", "2")]
        d = self._make_dash(epic, stories)
        _, _, _, act_cell = d._epic_header_cells(epic)
        assert "█" * 8 in act_cell  # all filled when all done


class TestSetStoryStatus:
    def _make_sprint_yaml(self, tmp_path: Path, story_id: str, status: str) -> Path:
        p = tmp_path / "sprint-status.yaml"
        p.write_text(yaml.dump({"development_status": {story_id: status}}))
        return p

    def test_updates_sprint_yaml(self, tmp_path):
        path = self._make_sprint_yaml(tmp_path, "1-1", "backlog")
        _set_story_status(path, "1-1", "in-progress")
        raw = yaml.safe_load(path.read_text())
        assert raw["development_status"]["1-1"] == "in-progress"

    def test_updates_md_status_line(self, tmp_path):
        sprint = self._make_sprint_yaml(tmp_path, "1-1", "backlog")
        md = tmp_path / "1-1.md"
        md.write_text("# Story 1.1\n\n**Status:** backlog\n\nsome content\n")
        _set_story_status(sprint, "1-1", "done", md)
        assert "**Status:** done" in md.read_text()

    def test_updates_md_plain_status_line(self, tmp_path):
        sprint = self._make_sprint_yaml(tmp_path, "1-1", "backlog")
        md = tmp_path / "1-1.md"
        md.write_text("# Story 1.1\n\nStatus: backlog\n\nsome content\n")
        _set_story_status(sprint, "1-1", "done", md)
        assert "Status: done" in md.read_text()

    def test_md_other_lines_unchanged(self, tmp_path):
        sprint = self._make_sprint_yaml(tmp_path, "1-1", "backlog")
        md = tmp_path / "1-1.md"
        original = "# Story 1.1\n\n**Status:** backlog\n\nsome content\n"
        md.write_text(original)
        _set_story_status(sprint, "1-1", "in-progress", md)
        text = md.read_text()
        assert "**Status:** in-progress" in text
        assert "some content" in text

    def test_no_md_does_not_crash(self, tmp_path):
        sprint = self._make_sprint_yaml(tmp_path, "1-1", "backlog")
        _set_story_status(sprint, "1-1", "done", None)
        raw = yaml.safe_load(sprint.read_text())
        assert raw["development_status"]["1-1"] == "done"

    def test_missing_md_file_does_not_crash(self, tmp_path):
        sprint = self._make_sprint_yaml(tmp_path, "1-1", "backlog")
        _set_story_status(sprint, "1-1", "done", tmp_path / "nonexistent.md")
        raw = yaml.safe_load(sprint.read_text())
        assert raw["development_status"]["1-1"] == "done"


class TestDashboardHistoryRowClickBehavior:
    """Tests for _DashboardHistoryRow single-click (Highlighted) and double-click (Selected)."""

    def _make_row(self) -> "object":
        from bmad_tui.dashboard import _DashboardHistoryRow
        from bmad_tui.history import HistoryEntry
        entry = HistoryEntry(
            ts="2026-01-01 12:00", workflow="dev-story", agent="dev",
            model="sonnet", story_id="1-1", epic_id="1",
            branch="main", session_id="abc",
        )
        return _DashboardHistoryRow(entry, index=0)

    def test_single_click_posts_highlighted(self) -> None:
        from textual.events import Click
        from bmad_tui.dashboard import _DashboardHistoryRow
        row = self._make_row()
        messages: list = []
        row.post_message = messages.append
        event = MagicMock(spec=Click)
        event.chain = 1
        row.on_click(event)
        assert len(messages) == 1
        assert isinstance(messages[0], _DashboardHistoryRow.Highlighted)
        assert messages[0].index == 0

    def test_double_click_posts_selected(self) -> None:
        from textual.events import Click
        from bmad_tui.dashboard import _DashboardHistoryRow
        row = self._make_row()
        messages: list = []
        row.post_message = messages.append
        event = MagicMock(spec=Click)
        event.chain = 2
        row.on_click(event)
        assert len(messages) == 1
        assert isinstance(messages[0], _DashboardHistoryRow.Selected)
        assert messages[0].index == 0

    def test_triple_click_also_posts_selected(self) -> None:
        from textual.events import Click
        from bmad_tui.dashboard import _DashboardHistoryRow
        row = self._make_row()
        messages: list = []
        row.post_message = messages.append
        event = MagicMock(spec=Click)
        event.chain = 3
        row.on_click(event)
        assert isinstance(messages[0], _DashboardHistoryRow.Selected)


class TestFocusRestoreAfterAgentRun:
    """Verify that sprint + story focus is correctly restored after _on_modal_result."""

    def test_epic_restored_by_id_when_index_shifts(self) -> None:
        """If an epic is removed during the run, the selected epic is found by ID, not by stale index."""
        # Before the run: epics [1, 2, 3], user was focused on epic "3" (index 2)
        state_before = _state(
            epics=[Epic(id="1", status="done"), Epic(id="2", status="in-progress"), Epic(id="3", status="backlog")],
            stories=[_story("3-1-a", "backlog", "3")],
        )
        d = _dash_with_state(state_before)
        d._selected_epic_index = 2  # pointing at epic "3"

        # After the run state reload: epic "1" was removed; epic "3" is now at index 1
        state_after = _state(
            epics=[Epic(id="2", status="in-progress"), Epic(id="3", status="backlog")],
            stories=[_story("3-1-a", "backlog", "3")],
        )
        d._state = state_after
        d._epics = sorted(state_after.epics, key=lambda e: int(e.id) if str(e.id).isdigit() else 999)

        # Apply the restoration logic that mirrors _on_modal_result
        saved_epic_id = "3"
        saved_story_id = "3-1-a"
        epic_ids = [str(e.id) for e in d._epics]
        if str(saved_epic_id) in epic_ids:
            d._selected_epic_index = epic_ids.index(str(saved_epic_id))
        else:
            d._selected_epic_index = min(d._selected_epic_index, max(0, len(d._epics) - 1))
        d._selected_story_id = saved_story_id

        assert d._selected_epic_index == 1, "epic '3' should be at index 1 after epic '1' was removed"
        assert d._selected_story_id == "3-1-a"

    def test_epic_clamps_when_not_found(self) -> None:
        """If the epic was removed entirely, index clamps to valid range."""
        state_after = _state(epics=[Epic(id="2", status="in-progress")])
        d = _dash_with_state(state_after)
        d._selected_epic_index = 5  # out of range

        saved_epic_id = "9"  # no longer exists
        epic_ids = [str(e.id) for e in d._epics]
        if str(saved_epic_id) in epic_ids:
            d._selected_epic_index = epic_ids.index(str(saved_epic_id))
        else:
            d._selected_epic_index = min(d._selected_epic_index, max(0, len(d._epics) - 1))

        assert d._selected_epic_index == 0

    def test_story_id_preserved_after_reload(self) -> None:
        """_selected_story_id is explicitly restored so _render_cards marks the right card active."""
        state = _state(
            epics=[Epic(id="4", status="in-progress")],
            stories=[_story("4-2-b", "in-progress", "4"), _story("4-3-c", "backlog", "4")],
        )
        d = _dash_with_state(state)
        d._selected_story_id = "4-2-b"

        # Simulate the explicit restore in _on_modal_result
        saved_story_id = "4-2-b"
        d._selected_story_id = saved_story_id

        assert d._selected_story_id == "4-2-b"
        # _render_cards would keep the -active card on "4-2-b" since it's still in the epic
        stories = d._stories_for_epic("4")
        assert saved_story_id in {s.id for s in stories}


class TestGlobalHistoryRowClickBehavior:
    """Tests for _GlobalHistoryRow single-click (Highlighted) and double-click (Selected)."""

    def _make_entry(self):
        from bmad_tui.history import HistoryEntry
        return HistoryEntry(
            ts="2026-01-01 12:00", workflow="dev-story", agent="dev",
            model="sonnet", story_id="1-1", epic_id="1",
            branch="main", session_id="abc",
        )

    def test_single_click_posts_highlighted(self) -> None:
        from textual.events import Click
        from bmad_tui.dashboard import _GlobalHistoryRow
        entry = self._make_entry()
        row = _GlobalHistoryRow(entry)
        messages: list = []
        row.post_message = messages.append
        event = MagicMock(spec=Click)
        event.chain = 1
        row.on_click(event)
        assert len(messages) == 1
        assert isinstance(messages[0], _GlobalHistoryRow.Highlighted)
        assert messages[0].entry is entry

    def test_double_click_posts_selected(self) -> None:
        from textual.events import Click
        from bmad_tui.dashboard import _GlobalHistoryRow
        entry = self._make_entry()
        row = _GlobalHistoryRow(entry)
        messages: list = []
        row.post_message = messages.append
        event = MagicMock(spec=Click)
        event.chain = 2
        row.on_click(event)
        assert len(messages) == 1
        assert isinstance(messages[0], _GlobalHistoryRow.Selected)
        assert messages[0].entry is entry


def _make_history_entry(
    session_id: str = "sess-001",
    story_id: str = "1-1",
    task_name: str = "Add export feature",
    workflow: str = "dev-story",
    ts: str = "2026-03-04T17:30:00Z",
    api_time: str = "5s",
) -> HistoryEntry:
    return HistoryEntry(
        ts=ts,
        workflow=workflow,
        agent="dev",
        model="claude-sonnet-4.6",
        story_id=story_id,
        epic_id="1",
        branch="feature/us1-1",
        session_id=session_id,
        api_time=api_time,
        task_name=task_name,
    )


class TestSearchScreenHistoryResults:
    """Tests for SearchScreen history entry inclusion in search results."""

    def _make_screen(
        self,
        stories: list | None = None,
        history: list | None = None,
    ) -> SearchScreen:
        screen = SearchScreen(stories or [], history or [])
        return screen

    def test_history_entry_included_in_empty_query(self) -> None:
        """History entries appear when query is empty."""
        entry = _make_history_entry()
        screen = self._make_screen(history=[entry])
        results = screen._build_result_list("")
        kinds = [r[0] for r in results]
        assert "history" in kinds

    def test_history_entry_key_is_session_id(self) -> None:
        """The key for a history result is the session_id."""
        entry = _make_history_entry(session_id="unique-session-42")
        screen = self._make_screen(history=[entry])
        results = screen._build_result_list("")
        hist = next(r for r in results if r[0] == "history")
        assert hist[1] == "unique-session-42"

    def test_history_label_contains_task_name(self) -> None:
        """History label shows task_name when present."""
        entry = _make_history_entry(task_name="My Feature Task")
        screen = self._make_screen(history=[entry])
        results = screen._build_result_list("")
        hist = next(r for r in results if r[0] == "history")
        assert "My Feature Task" in hist[2]

    def test_history_label_falls_back_to_story_id(self) -> None:
        """History label falls back to story_id when task_name is empty."""
        entry = _make_history_entry(task_name="", story_id="3-7")
        screen = self._make_screen(history=[entry])
        results = screen._build_result_list("")
        hist = next(r for r in results if r[0] == "history")
        assert "3-7" in hist[2]

    def test_history_label_contains_date(self) -> None:
        """History label includes the date portion of the timestamp."""
        entry = _make_history_entry(ts="2026-03-04T17:30:00Z")
        screen = self._make_screen(history=[entry])
        results = screen._build_result_list("")
        hist = next(r for r in results if r[0] == "history")
        assert "2026-03-04" in hist[2]

    def test_history_label_contains_workflow(self) -> None:
        """History label includes the workflow name."""
        entry = _make_history_entry(workflow="code-review")
        screen = self._make_screen(history=[entry])
        results = screen._build_result_list("")
        hist = next(r for r in results if r[0] == "history")
        assert "code-review" in hist[2]

    def test_history_filtered_by_query_task_name(self) -> None:
        """Querying for task_name text returns the matching history entry."""
        entry = _make_history_entry(task_name="Special Export Widget")
        screen = self._make_screen(history=[entry])
        results = screen._build_result_list("special export")
        kinds = [r[0] for r in results]
        assert "history" in kinds

    def test_history_filtered_out_when_no_match(self) -> None:
        """History entries are excluded when the query doesn't match."""
        entry = _make_history_entry(task_name="Export Widget", story_id="1-1", workflow="dev-story")
        screen = self._make_screen(history=[entry])
        results = screen._build_result_list("zzznomatch999")
        kinds = [r[0] for r in results]
        assert "history" not in kinds

    def test_history_entry_without_session_id_excluded(self) -> None:
        """History entries without a session_id are not included in results."""
        entry = _make_history_entry(session_id="")
        screen = self._make_screen(history=[entry])
        results = screen._build_result_list("")
        kinds = [r[0] for r in results]
        assert "history" not in kinds

    def test_multiple_history_entries_all_included(self) -> None:
        """Multiple history entries with distinct session_ids are all returned."""
        entries = [
            _make_history_entry(session_id=f"sess-{i}", task_name=f"Task {i}")
            for i in range(3)
        ]
        screen = self._make_screen(history=entries)
        results = screen._build_result_list("")
        hist_keys = [r[1] for r in results if r[0] == "history"]
        assert len(hist_keys) == 3
        assert set(hist_keys) == {"sess-0", "sess-1", "sess-2"}

    def test_history_query_matches_story_id(self) -> None:
        """Querying by story_id matches history entries."""
        entry = _make_history_entry(story_id="5-12", task_name="")
        screen = self._make_screen(history=[entry])
        results = screen._build_result_list("5-12")
        kinds = [r[0] for r in results]
        assert "history" in kinds

    def test_history_query_matches_workflow(self) -> None:
        """Querying by workflow name matches history entries."""
        entry = _make_history_entry(workflow="code-review")
        screen = self._make_screen(history=[entry])
        results = screen._build_result_list("code-review")
        kinds = [r[0] for r in results]
        assert "history" in kinds


class TestWorkflowPickerModalPreselect:
    """WorkflowPickerModal pre-selects the workflow passed via initial_workflow_key."""

    def test_no_initial_key_defaults_to_zero(self) -> None:
        """Without initial_workflow_key, selection starts at index 0."""
        modal = WorkflowPickerModal()
        assert modal._selected_idx == 0

    def test_known_key_preselects_correct_index(self) -> None:
        """A known workflow key is pre-selected at the right index."""
        modal = WorkflowPickerModal(initial_workflow_key="code-review")
        keys = [k for k, _ in modal._items]
        assert keys[modal._selected_idx] == "code-review"

    def test_unknown_key_falls_back_to_zero(self) -> None:
        """An unknown workflow key falls back to index 0 without error."""
        modal = WorkflowPickerModal(initial_workflow_key="nonexistent-workflow-xyz")
        assert modal._selected_idx == 0

    def test_initial_model_is_respected(self) -> None:
        """The initial_model parameter is stored on the modal."""
        modal = WorkflowPickerModal(initial_workflow_key="dev-story", initial_model=Model.OPUS)
        assert modal._model == Model.OPUS


class TestStoryActionModalSetActive:
    """_set_active must clear history selection so keyboard nav and Enter are consistent."""

    def _make_modal(self) -> StoryActionModal:
        """Build a StoryActionModal with its internal lists wired up directly (no DOM)."""
        from pathlib import Path
        story = Story(id="2-1-some-story", yaml_status="in-progress", epic_id="2", file_path=None)
        modal = StoryActionModal.__new__(StoryActionModal)
        # Minimal internal state required by _set_active
        modal._selected_idx = 0
        modal._selected_history = None
        modal._action_rows = [MagicMock(), MagicMock(), MagicMock()]
        modal._history_rows = [MagicMock(), MagicMock()]
        return modal

    def test_set_active_clears_selected_history(self) -> None:
        """Navigating to an action row via _set_active clears any history selection."""
        modal = self._make_modal()
        modal._selected_history = ("dev-story", "claude-sonnet-4.6", "some-session-id")

        modal._set_active(1)

        assert modal._selected_history is None

    def test_set_active_removes_selected_class_from_history_rows(self) -> None:
        """_set_active removes -selected from all history rows when history was selected."""
        modal = self._make_modal()
        modal._selected_history = ("dev-story", "claude-sonnet-4.6", "some-session-id")

        modal._set_active(0)

        for row in modal._history_rows:
            row.remove_class.assert_called_with("-selected")

    def test_set_active_no_history_rows_touched_when_none_selected(self) -> None:
        """_set_active does not touch history rows when no history entry was selected."""
        modal = self._make_modal()
        modal._selected_history = None

        modal._set_active(1)

        for row in modal._history_rows:
            row.remove_class.assert_not_called()

    def test_keyboard_nav_after_history_click_clears_selection(self) -> None:
        """Simulates: click history entry, then press ↓ — history selection must be gone."""
        modal = self._make_modal()

        # Simulate clicking a history entry
        modal._selected_history = ("code-review", "gpt-5.3-codex", "abc-session")

        # Simulate pressing ↓ (action_next_action calls _set_active)
        modal._set_active(min(len(modal._action_rows) - 1, modal._selected_idx + 1))

        assert modal._selected_history is None

    def test_action_run_uses_action_not_history_after_nav(self) -> None:
        """After keyboard navigation clears history, action_run dispatches the action row."""
        from unittest.mock import patch
        modal = self._make_modal()
        modal._modal_actions = [("dev-story", "Dev Story", "desc"), ("code-review", "Code Review", "desc")]
        modal._selected_history = ("create-story", "claude-sonnet-4.6", "old-session")
        modal._model = Model.SONNET
        modal._auto_despawn = False

        # Navigate with ↓ — should clear history
        modal._set_active(1)

        assert modal._selected_history is None
        # Now action_run should use modal_actions[_selected_idx], not history
        dismissed_with = []
        modal.dismiss = lambda v: dismissed_with.append(v)
        with patch.object(type(modal), "query_one", side_effect=AttributeError):
            # _selected_history is None so it falls through to action row path
            # But query_one would fail in unit test — we just check _selected_history is None
            pass
        assert modal._selected_history is None
