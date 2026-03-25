"""BMAD TUI Home View.

Home-only implementation matching the prototype layout:
- Header with centered tabs
- Left sprint selector
- Center task cards (4 per row)
- Right selected task details
- Bottom command bar
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable, ClassVar

from textual import events, on
from textual.app import App, ComposeResult
from textual.message import Message
from textual.screen import ModalScreen, Screen
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Footer, Input, Label, Markdown, Static
from rich.console import RenderableType

from .agent_runner import available_clis, check_prerequisites, run_workflow
from .config import TuiConfig, load_config, save_config
from .history import HistoryEntry, append_history, has_zero_code_changes, load_history, purge_legacy_entries, purge_trivial_entries
from .models import AgentDef, Epic, Model, ProjectState, STATUS_BADGES, Story, StoryStatus
from .state import _phase_summary, load_state, project_phase
from .workflows import AGENTS, CANONICAL_PHASES, STATUS_ACTIONS, WORKFLOWS, load_agents


def _current_git_branch(cwd: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=3,
        )
        branch = result.stdout.strip()
        return branch if branch else "unknown"
    except Exception:
        return "unknown"


class _ActionRow(Widget):
    """A clickable action row in the story action modal."""

    class Selected(Message):
        def __init__(self, idx: int) -> None:
            super().__init__()
            self.idx = idx

    def __init__(self, idx: int, label: str, desc: str, active: bool) -> None:
        super().__init__(classes="modal-action-row -active" if active else "modal-action-row")
        self._idx = idx
        self._label = label
        self._desc = desc

    def compose(self) -> ComposeResult:
        yield Static(self._label, classes="modal-action-label")
        yield Static(self._desc, classes="modal-action-desc")

    def on_click(self) -> None:
        self.post_message(self.Selected(self._idx))


class _MpoOption(Widget):
    """A clickable model option inside ModelPickerOverlay."""

    DEFAULT_CSS = """
    _MpoOption {
        height: 2;
        width: 1fr;
        padding: 0 2;
        align: left middle;
    }
    """

    class Selected(Message):
        def __init__(self, model: Model) -> None:
            super().__init__()
            self.model = model

    def __init__(self, model: Model, current: bool) -> None:
        super().__init__(classes="mpo-opt -current" if current else "mpo-opt")
        self._model = model

    def compose(self) -> ComposeResult:
        marker = "◀" if self.has_class("-current") else " "
        yield Static(f"{marker} {self._model.value}", classes="mpo-opt-label")

    def on_click(self) -> None:
        self.post_message(self.Selected(self._model))


class ModelPickerOverlay(ModalScreen):
    """Floating overlay for picking a model, anchored below the invoking row.
    Mirrors StatusDropdownOverlay — transparent background, positioned via styles.offset."""

    CSS = """
    ModelPickerOverlay {
        align: left top;
        background: rgba(0,0,0,0);
    }

    #mpo-outer {
        width: 40;
        height: auto;
        background: #0F172A;
        border: round #1E293B;
        padding: 0 0;
    }

    #mpo-header-label {
        height: 1;
        background: #1E293B;
        padding: 0 2;
        color: #64748B;
        content-align: left middle;
    }

    .mpo-opt {
        height: 2;
        width: 1fr;
        padding: 0 2;
        align: left middle;
    }

    .mpo-opt.-current {
        background: #1E293B;
    }

    .mpo-opt:hover {
        background: #172033;
    }

    .mpo-opt-label {
        color: #E5E7EB;
        content-align: left middle;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close", "Close", show=False),
    ]

    def __init__(self, current: Model, anchor: tuple[int, int, int, int] = (0, 0, 40, 3)) -> None:
        super().__init__()
        self._current = current
        self._anchor = anchor

    def compose(self) -> ComposeResult:
        with Container(id="mpo-outer"):
            yield Static("select model", id="mpo-header-label")
            for m in Model:
                yield _MpoOption(m, current=(m == self._current))

    def on_mount(self) -> None:
        ax, ay, aw, ah = self._anchor
        outer = self.query_one("#mpo-outer")
        outer.styles.offset = (ax, ay + ah)
        outer.styles.width = max(40, aw)

    def on__mpo_option_selected(self, event: _MpoOption.Selected) -> None:
        self.dismiss(event.model)

    def action_close(self) -> None:
        self.dismiss(None)

    def on_click(self, event: events.Click) -> None:
        if event.widget is self:
            self.dismiss(None)


class _ModelPicker(Widget):
    """Model label + trigger row. Clicking opens ModelPickerOverlay anchored below — same pattern as status picker."""

    class Changed(Message):
        def __init__(self, model: Model) -> None:
            super().__init__()
            self.model = model

    DEFAULT_CSS = """
    _ModelPicker {
        height: auto;
    }
    _ModelPicker .mp-label {
        color: #9CA3AF;
        margin-bottom: 0;
    }
    _ModelPicker .mp-row {
        height: 3;
        background: #0F172A;
        border: round #0F172A;
        padding: 0 1;
        align: left middle;
        margin-bottom: 1;
    }
    _ModelPicker .mp-val {
        color: #F8FAFC;
        text-style: bold;
        content-align: left middle;
        width: 1fr;
    }
    """

    def __init__(self, initial_model: Model = Model.SONNET) -> None:
        super().__init__()
        self._model = initial_model

    @property
    def model(self) -> Model:
        return self._model

    def compose(self) -> ComposeResult:
        yield Static("model", classes="mp-label")
        yield Horizontal(
            Static(f"{self._model.value}   ▼", classes="mp-val"),
            classes="mp-row",
        )

    def _open_overlay(self) -> None:
        row = self.query_one(".mp-row")
        r = row.region
        self.app.push_screen(
            ModelPickerOverlay(self._model, anchor=(r.x, r.y, r.width, r.height)),
            self._on_model_chosen,
        )

    def _on_model_chosen(self, model: Model | None) -> None:
        if model is None:
            return
        self.set_model(model)

    def set_model(self, model: Model) -> None:
        self._model = model
        self.query_one(".mp-val", Static).update(f"{model.value}   ▼")
        self.post_message(self.Changed(model))

    def toggle(self) -> None:
        self._open_overlay()

    def on_click(self, event) -> None:  # type: ignore[override]
        node = event.widget
        while node is not None and node is not self:
            if node.has_class("mp-row") or node.has_class("mp-val"):
                self._open_overlay()
                return
            node = getattr(node, "parent", None)



class _AgentCard(Widget):
    """A selectable agent card in the agent picker screen."""

    class Selected(Message):
        def __init__(self, agent: AgentDef) -> None:
            super().__init__()
            self.agent = agent

    def __init__(self, agent: AgentDef, active: bool = False) -> None:
        super().__init__(classes="agent-card -active" if active else "agent-card")
        self._agent = agent

    def compose(self) -> ComposeResult:
        yield Static(self._agent.icon, classes="agent-card-icon")
        yield Static(self._agent.role or self._agent.name, classes="agent-card-role")
        yield Static(self._agent.name, classes="agent-card-name")

    def on_click(self) -> None:
        self.post_message(self.Selected(self._agent))


def _modal_actions_for(yaml_status: str) -> list[tuple[str, str, str]]:
    """Return (key, label, description) tuples for the given story status."""
    effective = "backlog" if yaml_status == "needs-story" else yaml_status
    keys = STATUS_ACTIONS.get(effective, [])
    return [(k, WORKFLOWS[k].label, WORKFLOWS[k].description) for k in keys if k in WORKFLOWS]


class _HistoryEntryRow(Widget):
    """A clickable history entry row in the story action modal."""

    class Selected(Message):
        def __init__(self, workflow: str, model_str: str, session_id: str) -> None:
            super().__init__()
            self.workflow = workflow
            self.model_str = model_str
            self.session_id = session_id

    def __init__(self, entry_workflow: str, entry_model_str: str, ts: str, wf_label: str, session_id: str = "") -> None:
        super().__init__(classes="history-entry-row")
        self._workflow = entry_workflow
        self._model_str = entry_model_str
        self._ts = ts
        self._wf_label = wf_label
        self._session_id = session_id

    def compose(self) -> ComposeResult:
        icon = "↩ resume" if self._session_id else "▶ re-run"
        yield Static(self._ts, classes="history-entry-ts")
        yield Horizontal(
            Static(self._wf_label, classes="history-entry-wf"),
            Static(icon, classes="history-entry-rerun"),
        )

    def on_click(self) -> None:
        self.post_message(self.Selected(self._workflow, self._model_str, self._session_id))

    def on_mouse_enter(self) -> None:
        self.add_class("-hover")

    def on_mouse_leave(self) -> None:
        self.remove_class("-hover")


class _CheckboxRow(Widget):
    """A toggle row that displays a persistent boolean setting."""

    class Toggled(Message):
        def __init__(self, value: bool) -> None:
            super().__init__()
            self.value = value

    def __init__(self, label: str, value: bool) -> None:
        super().__init__(classes="checkbox-row")
        self._label = label
        self._value = value

    def compose(self) -> ComposeResult:
        mark = "X" if self._value else " "
        yield Static(f"\\[{mark}] {self._label}", classes="checkbox-text")

    def on_click(self) -> None:
        self._value = not self._value
        mark = "X" if self._value else " "
        self.query_one(".checkbox-text", Static).update(f"\\[{mark}] {self._label}")
        self.post_message(self.Toggled(self._value))


class StoryActionModal(ModalScreen):

    class StatusChanged(Message):
        """Posted when the user changes the story status from within the modal."""
        def __init__(self, story_id: str, status: StoryStatus) -> None:
            super().__init__()
            self.story_id = story_id
            self.status = status

    """Action picker modal matching the story_action_modal mockup."""

    CSS = """
    StoryActionModal {
        align: center middle;
    }

    #modal-outer {
        width: 80;
        background: #0B1220;
        border: round #0B1220;
        padding: 1 2;
        height: auto;
        max-height: 90vh;
    }

    #modal-outer.--has-history {
        width: 116;
    }

    #modal-outer.--has-content {
        width: 138;
    }

    #modal-outer.--has-content.--has-history {
        width: 176;
    }

    #modal-outer.--has-content.--content-expanded {
        width: 162;
    }

    #modal-outer.--has-content.--has-history.--content-expanded {
        width: 200;
    }

    #modal-body {
        width: 1fr;
        height: auto;
    }

    #modal-content-panel {
        width: 56;
        height: 32;
        border-right: solid #1F2937;
        padding-right: 2;
        margin-right: 2;
        overflow-y: auto;
    }

    #modal-content-panel.--expanded {
        width: 80;
        height: 50;
    }

    #modal-content-label {
        color: #6B7280;
        text-style: italic;
        margin-bottom: 1;
    }

    #modal-content-hint {
        color: #374151;
        margin-top: 1;
    }

    #modal-left {
        width: 74;
        height: auto;
    }

    #modal-history-panel {
        width: 36;
        margin-left: 2;
        height: auto;
        border-left: solid #1F2937;
        padding-left: 2;
    }

    #modal-history-label {
        color: #6B7280;
        text-style: italic;
        margin-bottom: 1;
    }

    #modal-history-box {
        background: transparent;
        height: auto;
        overflow-y: auto;
    }

    .history-entry-row {
        width: 1fr;
        height: 3;
        padding: 0 0;
        margin-bottom: 0;
    }

    .history-entry-row.-hover .history-entry-wf {
        color: #93C5FD;
        text-style: bold;
    }

    .history-entry-row.-selected .history-entry-wf {
        color: #60A5FA;
        text-style: bold;
    }

    .history-entry-row.-selected .history-entry-rerun {
        color: #22C55E;
    }

    .history-entry-ts {
        width: 1fr;
        color: #374151;
        content-align: left middle;
    }

    .history-entry-wf {
        width: 1fr;
        color: #64748B;
        content-align: left middle;
    }

    .history-entry-rerun {
        width: auto;
        color: #1F2937;
        content-align: right middle;
    }

    .history-entry-row.-hover .history-entry-rerun {
        color: #4B5563;
    }

    #modal-header {
        height: 3;
        padding: 0 1;
        margin-bottom: 1;
    }

    #modal-title {
        width: 1fr;
        color: #E5E7EB;
        text-style: bold;
        content-align: left middle;
    }

    #modal-close {
        width: auto;
        background: #1F2937;
        border: round #1F2937;
        color: #E5E7EB;
        padding: 0 1;
        content-align: center middle;
        height: 3;
    }

    #modal-meta {
        color: #94A3B8;
        margin-bottom: 1;
    }

    #modal-status-label {
        color: #9CA3AF;
        margin-bottom: 0;
    }

    #modal-status-row {
        height: 3;
        background: #0F172A;
        border: round #0F172A;
        padding: 0 1;
        margin-bottom: 1;
        align: left middle;
    }

    #modal-status-val {
        color: #E5E7EB;
        text-style: bold;
        width: 1fr;
        content-align: left middle;
    }

    #modal-actions-label {
        color: #22C55E;
        text-style: bold;
        margin-bottom: 1;
    }

    #modal-actions-box {
        background: #0F172A;
        border: round #0F172A;
        padding: 1 1;
        height: auto;
        margin-bottom: 1;
    }

    .modal-action-row {
        height: 3;
        width: 1fr;
        background: #111827;
        border: round #111827;
        padding: 0 1;
        align: left middle;
        margin-bottom: 1;
    }

    .modal-action-row.-active {
        background: #172033;
        border: round #172033;
    }

    .modal-action-row.-hover {
        background: #233047;
        border: round #233047;
    }

    .modal-action-label {
        width: auto;
        color: #CBD5E1;
        content-align: left middle;
    }

    .modal-action-row.-active .modal-action-label {
        color: #F8FAFC;
        text-style: bold;
    }

    .modal-action-desc {
        width: 1fr;
        color: #64748B;
        content-align: left middle;
    }

    #modal-hint {
        color: #64748B;
        margin-bottom: 1;
    }

    .checkbox-row {
        height: 1;
    }

    .checkbox-text {
        color: #94A3B8;
    }

    .checkbox-text:hover {
        color: #E2E8F0;
    }

    #modal-no-actions {
        color: #64748B;
        padding: 1 1;
    }

    #modal-btn-row {
        height: 3;
        align: left middle;
    }

    #modal-btn-row .checkbox-row {
        width: 1fr;
        height: 3;
    }

    #modal-btn-row .checkbox-text {
        height: 3;
        content-align: left middle;
    }

    #modal-btn-cancel {
        width: auto;
        background: #334155;
        border: round #334155;
        color: #E5E7EB;
        padding: 0 2;
        content-align: center middle;
        margin-right: 1;
    }

    #modal-btn-run {
        width: auto;
        background: #166534;
        border: round #166534;
        color: #E5E7EB;
        text-style: bold;
        padding: 0 2;
        content-align: center middle;
    }


    .modal-history-row {
        height: 2;
        padding: 0 0;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close", "Close", show=False),
        Binding("up", "prev_action", "Prev", show=False),
        Binding("down", "next_action", "Next", show=False),
        Binding("tab", "cycle_model", "Model", show=False),
        Binding("enter", "run", "Run", show=False),
        Binding("p", "toggle_content", "Expand content", show=False),
    ]

    def __init__(self, story: Story, model: Model, sprint_status_path: Path, project_root: Path | None = None, auto_despawn: bool = True) -> None:
        super().__init__()
        self._story = story
        self._sprint_status_path = sprint_status_path
        self._model = model
        self._project_root = project_root
        self._auto_despawn = auto_despawn
        self._current_status = story.effective_status
        self._modal_actions = _modal_actions_for(story.yaml_status)
        primary = story.primary_workflow or "dev-story"
        self._selected_idx = next(
            (i for i, (key, _, _) in enumerate(self._modal_actions) if key == primary), 0
        )
        self._action_rows: list[_ActionRow] = []
        self._history_rows: list[_HistoryEntryRow] = []
        self._selected_history: tuple[str, str, str] | None = None  # (workflow, model_str, session_id)
        # Story file content for the inline preview panel — always set, fallback if no file
        if story.file_path and Path(story.file_path).exists():
            try:
                self._story_content: str = Path(story.file_path).read_text(encoding="utf-8")
            except OSError:
                self._story_content = "_Could not read story file._"
        elif story.file_path:
            self._story_content = "_Story file not found._"
        else:
            self._story_content = "_No story document created yet._"
        self._has_file = bool(story.file_path and Path(story.file_path).exists())
        self._content_expanded = False
        # History entries for this story (most recent first)
        if project_root is not None:
            all_history = load_history(project_root)
            self._story_history = [e for e in reversed(all_history) if e.story_id == story.id]
        else:
            self._story_history = []

    _STATUS_OPTIONS = [
        StoryStatus.READY_FOR_DEV,
        StoryStatus.IN_PROGRESS,
        StoryStatus.REVIEW,
        StoryStatus.DONE,
        StoryStatus.BACKLOG,
        StoryStatus.BLOCKED,
    ]

    def compose(self) -> ComposeResult:
        story = self._story
        outer_classes = "--has-history" if self._story_history else ""
        if self._has_file:
            outer_classes = ("--has-content " + outer_classes).strip()
            if self._story_history:
                outer_classes = "--has-content --has-history"
        with Container(id="modal-outer", classes=outer_classes):
            with Horizontal(id="modal-header"):
                yield Static(f"actions // story {story.id}", id="modal-title")
                yield Static("esc ✕", id="modal-close")
            yield Static(f"epic: {story.epic_id}   |   press enter to run selected action", id="modal-meta")
            with Horizontal(id="modal-body"):
                if self._has_file:
                    with Container(id="modal-content-panel"):
                        yield Static("story content", id="modal-content-label")
                        yield Markdown(self._story_content, id="modal-content-md")
                        yield Static("[dim]p expand[/dim]", id="modal-content-hint")
                with Container(id="modal-left"):
                    yield Static("status", id="modal-status-label")
                    yield Horizontal(
                        Static(f"{self._current_status.emoji} {self._current_status.value}   ▼", id="modal-status-val"),
                        id="modal-status-row",
                    )
                    yield Static("available actions", id="modal-actions-label")
                    with Container(id="modal-actions-box"):
                        if self._modal_actions:
                            for i, (key, label, desc) in enumerate(self._modal_actions):
                                yield _ActionRow(i, label, desc, active=(i == self._selected_idx))
                        else:
                            yield Static("No actions available for this status.", id="modal-no-actions")
                    yield _ModelPicker(self._model)
                    yield Static("↑/↓ select action   tab model   enter run   esc close", id="modal-hint")
                    with Horizontal(id="modal-btn-row"):
                        yield _CheckboxRow("auto-despawn on finish", self._auto_despawn)
                        yield Static("Cancel", id="modal-btn-cancel")
                        yield Static("Run Action", id="modal-btn-run")
                if self._story_history:
                    with Container(id="modal-history-panel"):
                        yield Static("run history", id="modal-history-label")
                        with Container(id="modal-history-box"):
                            for entry in self._story_history[:8]:
                                ts = entry.ts[:16].replace("T", " ") if len(entry.ts) >= 16 else entry.ts
                                wf_label = WORKFLOWS[entry.workflow].label if entry.workflow in WORKFLOWS else entry.workflow
                                yield _HistoryEntryRow(entry.workflow, entry.model, ts, wf_label, entry.session_id)

    def on_mount(self) -> None:
        self._action_rows = list(self.query(_ActionRow))
        self._history_rows = list(self.query(_HistoryEntryRow))

    def _set_active(self, idx: int) -> None:
        old = self._selected_idx
        self._selected_idx = idx
        if 0 <= old < len(self._action_rows):
            self._action_rows[old].remove_class("-active")
        if 0 <= idx < len(self._action_rows):
            self._action_rows[idx].add_class("-active")
        # Activating an action row always clears any in-flight history selection so
        # that Enter runs the action the user navigated to, not the history entry.
        if self._selected_history is not None:
            self._selected_history = None
            for row in self._history_rows:
                row.remove_class("-selected")

    def _toggle_dropdown(self) -> None:
        self.query_one(_ModelPicker).toggle()

    def _select_model(self, model: Model) -> None:
        self.query_one(_ModelPicker).set_model(model)
        self._model = model

    def _open_status_overlay(self) -> None:
        row = self.query_one("#modal-status-row")
        r = row.region
        self.app.push_screen(
            StatusDropdownOverlay(self._current_status, anchor=(r.x, r.y, r.width, r.height)),
            self._on_status_chosen,
        )

    def _on_status_chosen(self, status: StoryStatus | None) -> None:
        if status is None:
            return
        self._current_status = status
        self.query_one("#modal-status-val", Static).update(
            f"{status.emoji} {status.value}   ▼"
        )
        try:
            _set_story_status(self._sprint_status_path, self._story.id, status.value, self._story.file_path)
        except Exception:
            pass
        # Notify the dashboard so the card and sidebar update without a full refresh
        self.post_message(StoryActionModal.StatusChanged(self._story.id, status))
        # Rebuild the action list for the new status
        self._refresh_actions(status.value)

    def _refresh_actions(self, yaml_status: str) -> None:
        """Rebuild the actions box to match the new status."""
        self._modal_actions = _modal_actions_for(yaml_status)
        self._selected_idx = 0
        box = self.query_one("#modal-actions-box", Container)
        box.remove_children()
        if self._modal_actions:
            for i, (key, label, desc) in enumerate(self._modal_actions):
                row = _ActionRow(i, label, desc, active=(i == 0))
                box.mount(row)
        else:
            box.mount(Static("No actions available for this status.", id="modal-no-actions"))
        self._action_rows = list(self.query(_ActionRow))

    def on__model_picker_changed(self, message: _ModelPicker.Changed) -> None:
        # Keep self._model in sync for history-entry fallback usage
        self._model = message.model

    def on__action_row_selected(self, message: _ActionRow.Selected) -> None:
        self._set_active(message.idx)
        # Clear any history entry selection
        self._selected_history = None
        for row in self._history_rows:
            row.remove_class("-selected")

    def on__history_entry_row_selected(self, message: _HistoryEntryRow.Selected) -> None:
        # Select/highlight the history entry — Run button will execute it
        self._selected_history = (message.workflow, message.model_str, message.session_id)
        for row in self._history_rows:
            is_match = (row._workflow == message.workflow and row._session_id == message.session_id)
            row.set_class(is_match, "-selected")
        # Visually deselect action rows without changing the saved index
        for row in self._action_rows:
            row.remove_class("-active")

    def on__checkbox_row_toggled(self, message: _CheckboxRow.Toggled) -> None:
        self._auto_despawn = message.value

    def action_prev_action(self) -> None:
        self._set_active(max(0, self._selected_idx - 1))

    def action_next_action(self) -> None:
        self._set_active(min(len(self._modal_actions) - 1, self._selected_idx + 1))

    def action_cycle_model(self) -> None:
        self._toggle_dropdown()

    def action_run(self) -> None:
        if self._selected_history is not None:
            workflow, model_str, session_id = self._selected_history
            try:
                model = Model(model_str)
            except ValueError:
                model = self.query_one(_ModelPicker).model
            self.dismiss((workflow, model, session_id, self._auto_despawn))
            return
        if not self._modal_actions:
            return
        key, label, _ = self._modal_actions[self._selected_idx]
        self.dismiss((key, self.query_one(_ModelPicker).model, "", self._auto_despawn))

    def action_close(self) -> None:
        self.dismiss(None)

    def action_toggle_content(self) -> None:
        if not self._has_file:
            return
        self._content_expanded = not self._content_expanded
        panel = self.query_one("#modal-content-panel")
        outer = self.query_one("#modal-outer")
        if self._content_expanded:
            panel.add_class("--expanded")
            outer.add_class("--content-expanded")
        else:
            panel.remove_class("--expanded")
            outer.remove_class("--content-expanded")

    def on_click(self, event: events.Click) -> None:
        node_id = getattr(event.widget, "id", None) or ""
        parent_id = getattr(getattr(event.widget, "parent", None), "id", None) or ""
        # Close when clicking the backdrop (the ModalScreen itself)
        if event.widget is self:
            self.action_close()
            return
        if node_id == "modal-btn-cancel" or node_id == "modal-close":
            self.action_close()
        elif node_id == "modal-btn-run":
            self.action_run()
        elif node_id in ("modal-status-row", "modal-status-val") or parent_id == "modal-status-row":
            self._open_status_overlay()


class WorkflowPickerModal(ModalScreen):
    """Workflow browser modal sourced from BMAD workflow registry."""

    CSS = """
    WorkflowPickerModal {
        align: center middle;
    }

    #wf-outer {
        width: 110;
        height: auto;
        max-height: 46;
        background: #0B1220;
        border: round #0B1220;
        padding: 1 2;
    }

    #wf-header {
        height: 3;
        margin-bottom: 1;
    }

    #wf-title {
        width: 1fr;
        color: #E5E7EB;
        text-style: bold;
        content-align: left middle;
    }

    #wf-close {
        width: auto;
        background: #1F2937;
        border: round #1F2937;
        color: #E5E7EB;
        padding: 0 1;
        content-align: center middle;
        height: 3;
    }

    #wf-sub {
        color: #94A3B8;
        margin-bottom: 1;
    }

    #wf-scroll {
        height: 22;
        background: #0F172A;
        border: round #0F172A;
        padding: 1;
    }

    #wf-list {
        width: 1fr;
        height: auto;
    }

    .wf-row {
        height: 8;
        width: 1fr;
    }

    .wf-gap {
        width: 1;
    }

    .wf-row-gap {
        height: 1;
        width: 1fr;
    }

    .workflow-card {
        width: 1fr;
        height: 8;
        background: #111827;
        padding: 1;
    }

    .workflow-card.-active {
        background: #172033;
    }

    .workflow-card.-hover {
        background: #233047;
    }

    .workflow-title {
        color: #F8FAFC;
        text-style: bold;
    }

    .workflow-meta {
        color: #94A3B8;
    }

    .workflow-agent {
        color: #9CA3AF;
    }

    .workflow-model {
        color: #64748B;
    }

    #wf-hint {
        color: #64748B;
        margin-top: 1;
        margin-bottom: 1;
    }

    #wf-btn-row {
        height: 3;
        align: right middle;
    }

    #wf-btn-cancel {
        width: auto;
        background: #334155;
        border: round #334155;
        color: #E5E7EB;
        padding: 0 2;
        content-align: center middle;
        margin-right: 1;
    }

    #wf-btn-confirm {
        width: auto;
        background: #166534;
        border: round #166534;
        color: #E5E7EB;
        text-style: bold;
        padding: 0 2;
        content-align: center middle;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close", "Close", show=False),
        Binding("left", "left", "Left", show=False),
        Binding("right", "right", "Right", show=False),
        Binding("up", "up", "Up", show=False),
        Binding("down", "down", "Down", show=False),
        Binding("enter", "run", "Run", show=False),
        Binding("tab", "cycle_model", "Model", show=False),
    ]

    def __init__(self, agent: AgentDef | None = None, initial_model: Model = Model.SONNET, initial_workflow_key: str | None = None) -> None:
        super().__init__()
        self._agent = agent
        self._model = initial_model
        phase_order = {phase: i for i, phase in enumerate(CANONICAL_PHASES)}
        source = (
            {k: WORKFLOWS[k] for k in agent.workflow_keys if k in WORKFLOWS}
            if agent else WORKFLOWS
        )
        self._items = sorted(
            source.items(),
            key=lambda kv: (phase_order.get(kv[1].bmad_phase, 999), kv[1].label.lower()),
        )
        self._selected_idx = 0
        if initial_workflow_key is not None:
            for i, (k, _) in enumerate(self._items):
                if k == initial_workflow_key:
                    self._selected_idx = i
                    break
        self._cards: list[Container] = []
        self._hovered_card_idx: int | None = None

    def compose(self) -> ComposeResult:
        title = f"{self._agent.name} workflows" if self._agent else "workflows"
        with Container(id="wf-outer"):
            with Horizontal(id="wf-header"):
                yield Static(title, id="wf-title")
                yield Static("esc ✕", id="wf-close")
            yield Static(f"{len(self._items)} workflows · select one to continue", id="wf-sub")
            with VerticalScroll(id="wf-scroll"):
                with Container(id="wf-list"):
                    row_count = (len(self._items) + 3) // 4
                    for row_idx in range(row_count):
                        base = row_idx * 4
                        row_children = []
                        for col in range(4):
                            idx = base + col
                            if idx < len(self._items):
                                key, wf = self._items[idx]
                                classes = "workflow-card -active" if idx == self._selected_idx else "workflow-card"
                                card = Container(
                                    Static(wf.label, classes="workflow-title"),
                                    Static(wf.bmad_phase, classes="workflow-meta"),
                                    Static(wf.persona, classes="workflow-agent"),
                                    Static(
                                        f"{wf.default_model.label()}{' · locked' if wf.model_locked else ''}",
                                        classes="workflow-model",
                                    ),
                                    classes=classes,
                                )
                                setattr(card, "_wf_index", idx)
                                row_children.append(card)
                            else:
                                row_children.append(Container(classes="workflow-card"))
                            if col < 3:
                                row_children.append(Container(classes="wf-gap"))
                        yield Horizontal(*row_children, classes="wf-row")
                        if row_idx < row_count - 1:
                            yield Container(classes="wf-row-gap")
            yield Static("↑↓←→ move   enter run   tab model   esc close", id="wf-hint")
            yield _ModelPicker(self._model)
            with Horizontal(id="wf-btn-row"):
                yield Static("Cancel", id="wf-btn-cancel")
                yield Static("Run Workflow", id="wf-btn-confirm")

    def on_mount(self) -> None:
        self._cards = list(self.query(".workflow-card"))
        if self._selected_idx > 0 and self._selected_idx < len(self._cards):
            self._cards[self._selected_idx].scroll_visible(top=False)

    def _set_active(self, idx: int) -> None:
        idx = max(0, min(len(self._items) - 1, idx))
        old = self._selected_idx
        if old == idx:
            return
        if 0 <= old < len(self._cards):
            self._cards[old].remove_class("-active")
        self._selected_idx = idx
        if 0 <= idx < len(self._cards):
            self._cards[idx].add_class("-active")
            self._cards[idx].scroll_visible(top=False)

    def action_left(self) -> None:
        self._set_active(self._selected_idx - 1)

    def action_right(self) -> None:
        self._set_active(self._selected_idx + 1)

    def action_up(self) -> None:
        self._set_active(self._selected_idx - 4)

    def action_down(self) -> None:
        self._set_active(self._selected_idx + 4)

    def action_run(self) -> None:
        key, _wf = self._items[self._selected_idx]
        self.dismiss((key, self.query_one(_ModelPicker).model))

    def action_close(self) -> None:
        self.dismiss(None)

    def action_cycle_model(self) -> None:
        picker = self.query_one(_ModelPicker)
        models = list(Model)
        picker.set_model(models[(models.index(picker.model) + 1) % len(models)])

    def _find_wf_card(self, widget) -> tuple[Container, int] | None:
        """Walk up the widget tree to find a workflow card with _wf_index."""
        current = widget
        while current is not None:
            idx = getattr(current, "_wf_index", None)
            if idx is not None:
                return current, int(idx)
            current = getattr(current, "parent", None)
        return None

    def _set_hover(self, idx: int | None) -> None:
        if self._hovered_card_idx == idx:
            return
        if self._hovered_card_idx is not None and 0 <= self._hovered_card_idx < len(self._cards):
            self._cards[self._hovered_card_idx].remove_class("-hover")
        self._hovered_card_idx = idx
        if idx is not None and 0 <= idx < len(self._cards):
            card = self._cards[idx]
            if not card.has_class("-active"):
                card.add_class("-hover")

    def on_mouse_move(self, event: events.MouseMove) -> None:
        result = self._find_wf_card(event.widget)
        self._set_hover(result[1] if result else None)

    def on_mouse_leave(self, event: events.MouseLeave) -> None:
        self._set_hover(None)

    def on_click(self, event) -> None:  # type: ignore[override]
        if event.widget is self:
            self.action_close()
            return
        node_id = getattr(event.widget, "id", None) or ""
        if node_id in ("wf-close", "wf-btn-cancel"):
            self.action_close()
            return
        if node_id == "wf-btn-confirm":
            self.action_run()
            return
        result = self._find_wf_card(event.widget)
        if result is not None:
            _, idx = result
            self._set_active(idx)


class AgentPickerScreen(Screen):
    """Full-screen agent picker — same visual language as the Dashboard."""

    CSS = """
    AgentPickerScreen {
        background: #0C0C0C;
        color: #E5E7EB;
    }

    #ap-root {
        layout: vertical;
        padding: 1;
        height: 1fr;
        width: 1fr;
    }

    #ap-header {
        height: 5;
        background: #111111;
        border: round #111111;
        padding: 0 1;
    }

    #ap-header-title {
        width: auto;
        color: #22C55E;
        text-style: bold;
        content-align: left middle;
        margin-right: 2;
    }

    #ap-header-left {
        width: auto;
        height: 1fr;
        layout: vertical;
        margin-right: 2;
    }

    #ap-header-branch {
        width: auto;
        color: #6B7280;
        content-align: left middle;
    }

    #ap-header-tabs-area {
        width: 1fr;
        height: 1fr;
        layout: horizontal;
    }

    .ap-header-fill {
        width: 1fr;
        height: 1fr;
    }

    #ap-header-tabs {
        width: auto;
        height: 1fr;
    }

    .ap-tab-chip {
        background: #111111;
        color: #9CA3AF;
        padding: 0 2;
        margin: 0 1;
        height: 1fr;
        width: auto;
        content-align: center middle;
    }

    .ap-tab-chip.-active {
        background: #172033;
        color: #E5E7EB;
        text-style: bold;
    }

    .ap-tab-chip.-hover {
        background: #1F2937;
    }

    #ap-phase-banner {
        height: 3;
        background: #111111;
        padding: 0 1;
    }

    #ap-phase-banner-filler {
        width: auto;
        color: #111111;
        margin-right: 2;
        content-align: left middle;
    }

    #ap-phase-banner-text {
        width: 1fr;
        color: #9CA3AF;
        content-align: center middle;
    }

    #ap-body {
        height: 1fr;
        width: 1fr;
        margin-top: 1;
    }

    #ap-left {
        width: 40;
        height: 1fr;
        background: #101010;
        border: round #101010;
        padding: 1 2;
    }

    .ap-section-title {
        color: #22C55E;
        text-style: bold;
        margin-bottom: 1;
    }

    .ap-separator {
        color: #252525;
        margin-bottom: 1;
    }

    #ap-agent-icon {
        width: 1fr;
        content-align: center middle;
        height: 3;
        color: #E5E7EB;
        margin-bottom: 1;
    }

    #ap-agent-name {
        width: 1fr;
        content-align: center middle;
        height: 1;
        color: #E5E7EB;
        text-style: bold;
        margin-bottom: 0;
    }

    #ap-agent-role {
        width: 1fr;
        content-align: center middle;
        height: 1;
        color: #22C55E;
        text-style: bold;
        margin-bottom: 1;
    }

    #ap-agent-desc {
        color: #94A3B8;
        height: auto;
        margin-bottom: 1;
    }

    #ap-agent-tasks-label {
        color: #64748B;
        text-style: bold;
        height: 1;
        margin-bottom: 1;
    }

    #ap-agent-tasks {
        color: #94A3B8;
        height: auto;
    }

    #ap-center {
        width: 1fr;
        height: 1fr;
        background: #121212;
        border: round #121212;
        padding: 1 1;
        margin-left: 1;
    }

    #ap-center-title {
        color: #E5E7EB;
        text-style: bold;
        margin-bottom: 0;
    }

    #ap-center-sub {
        color: #94A3B8;
        margin-bottom: 1;
    }

    #ap-cards-scroll {
        height: 1fr;
    }

    #ap-cards-grid {
        width: 1fr;
        height: auto;
    }

    .ap-cards-row {
        width: 1fr;
        height: 11;
    }

    .ap-card-gap {
        width: 2;
    }

    .ap-row-gap {
        width: 1fr;
        height: 1;
    }

    .agent-card {
        width: 1fr;
        height: 11;
        background: #171717;
        layout: vertical;
        align: center middle;
        padding: 1 2;
    }

    .agent-card.-active {
        background: #1A2536;
    }

    .agent-card.-hover {
        background: #1f2937;
    }

    .agent-card.-empty {
        background: #121212;
    }

    .agent-card-icon {
        width: 1fr;
        content-align: center middle;
        height: 3;
        color: #E5E7EB;
    }

    .agent-card-role {
        width: 1fr;
        content-align: center middle;
        height: 2;
        color: #22C55E;
        text-style: bold;
    }

    .agent-card-name {
        width: 1fr;
        content-align: center middle;
        height: 1;
        color: #6B7280;
    }

    #ap-bottom-nav {
        height: 3;
        margin-top: 1;
        background: #111111;
        border: round #111111;
        padding: 0 1;
        layout: horizontal;
    }

    #ap-bottom-text {
        width: 1fr;
        content-align: left middle;
    }

    .ap-category-label {
        width: 1fr;
        height: 2;
        color: #4B5563;
        text-style: bold;
        content-align: left middle;
        padding: 0 1;
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close", "Close", show=False),
        Binding("left", "move_left", "Left", show=False),
        Binding("right", "move_right", "Right", show=False),
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("enter", "confirm", "Confirm", show=False),
        Binding("tab", "cycle_model", "Model", show=False),
    ]

    def __init__(self, project_root: Path, branch: str, state: "ProjectState", initial_idx: int = 0) -> None:
        super().__init__()
        self._project_root = project_root
        self._branch = branch
        self._state = state
        all_agents = load_agents(project_root)
        self._sprint_agents = [a for a in all_agents if a.category == "sprint"]
        self._other_agents = [a for a in all_agents if a.category != "sprint"]
        # Flattened list matching card display order (sprint first, then other)
        self._agents = self._sprint_agents + self._other_agents
        self._selected_idx = initial_idx
        self._cards: list[_AgentCard] = []
        self._hovered_card_idx: int | None = None
        self._hovered_ap_tab: Static | None = None
        self._pending_agent: "AgentDef | None" = None

    def _build_phase_banner_text(self) -> str:
        phase = project_phase(self._state)
        summary = _phase_summary(self._state)
        _phase_markup = {
            "retrospective": "[bold yellow]★ retrospective[/bold yellow]",
            "planning":      "[bold blue]→ planning[/bold blue]",
            "analysis":      "[bold red]○ analysis[/bold red]",
        }
        parts = []
        if phase in _phase_markup:
            parts.append(_phase_markup[phase])
        parts.append(f"{summary['active_epics']} active epics")
        if summary["in_review"]:
            parts.append(f"[bold magenta]{summary['in_review']} in review[/bold magenta]")
        if summary["pending_retros"]:
            parts.append(f"{summary['pending_retros']} retros pending")
        return "  ·  ".join(parts)

    def _compose_agent_section(
        self,
        agents: "list[AgentDef]",
        label: "str | None",
        global_offset: int,
    ) -> "ComposeResult":
        """Yield rows for a category section, padded to 5-column rhythm."""
        from textual.app import ComposeResult as CR  # local to avoid circular
        if label:
            yield Static(label, classes="ap-category-label")
        padded: list = list(agents)
        while len(padded) % 5 != 0:
            padded.append(None)
        row_count = len(padded) // 5
        for row_index, i in enumerate(range(0, len(padded), 5)):
            row_items = padded[i:i + 5]
            row_children: list = []
            for j, item in enumerate(row_items):
                flat_idx = global_offset + i + j
                if item is None:
                    row_children.append(Container(classes="agent-card -empty"))
                else:
                    row_children.append(_AgentCard(item, active=(flat_idx == self._selected_idx)))
                if j < 4:
                    row_children.append(Container(classes="ap-card-gap"))
            yield Horizontal(*row_children, classes="ap-cards-row")
            if row_index < row_count - 1:
                yield Container(classes="ap-row-gap")

    def compose(self) -> ComposeResult:
        with Container(id="ap-root"):
            with Horizontal(id="ap-header"):
                with Vertical(id="ap-header-left"):
                    yield Static(f"~ {self._project_root.name} board", id="ap-header-title")
                    yield Static(f"⎇  {self._branch}", id="ap-header-branch")
                with Horizontal(id="ap-header-tabs-area"):
                    yield Static("", classes="ap-header-fill")
                    with Horizontal(id="ap-header-tabs"):
                        yield Static("Sprint", classes="ap-tab-chip", id="ap-tab-sprint")
                        yield Static("Agents", classes="ap-tab-chip -active", id="ap-tab-agents-tab")
                        yield Static("History", classes="ap-tab-chip", id="ap-tab-history")

                    yield Static("", classes="ap-header-fill")

            with Horizontal(id="ap-phase-banner"):
                yield Static(f"~ {self._project_root.name} board", id="ap-phase-banner-filler")
                yield Static(self._build_phase_banner_text(), id="ap-phase-banner-text")

            with Horizontal(id="ap-body"):
                with Container(id="ap-left"):
                    yield Static("> agent info", classes="ap-section-title")
                    yield Static("─" * 34, classes="ap-separator")
                    yield Static("", id="ap-agent-icon")
                    yield Static("", id="ap-agent-name")
                    yield Static("", id="ap-agent-role")
                    yield Static("", id="ap-agent-desc")
                    yield Static("", id="ap-agent-tasks-label")
                    yield Static("", id="ap-agent-tasks")

                with Container(id="ap-center"):
                    yield Static("> agents", id="ap-center-title")
                    yield Static("click to preview  ·  double-click or enter to confirm", id="ap-center-sub")
                    with VerticalScroll(id="ap-cards-scroll"):
                        with Container(id="ap-cards-grid"):
                            yield from self._compose_agent_section(self._sprint_agents, "── Sprint", 0)
                            if self._other_agents:
                                sprint_offset = len(self._sprint_agents)
                                yield Static("── Other", classes="ap-category-label")
                                yield from self._compose_agent_section(self._other_agents, None, sprint_offset)

            with Horizontal(id="ap-bottom-nav"):
                yield Static(
                    "[green]↑↓←→[/] navigate  [green]enter[/] confirm  "
                    "[green]tab[/] model  [green]esc[/] back",
                    id="ap-bottom-text",
                )
                yield _ModelPicker()

    def on_mount(self) -> None:
        self._cards = list(self.query(_AgentCard))
        if self._cards:
            self._update_sidebar(self._agents[self._selected_idx])

    def _update_sidebar(self, agent: AgentDef) -> None:
        self.query_one("#ap-agent-icon", Static).update(agent.icon)
        self.query_one("#ap-agent-name", Static).update(agent.name)
        self.query_one("#ap-agent-role", Static).update(agent.role)
        self.query_one("#ap-agent-desc", Static).update(agent.description)
        tasks = "\n".join(
            f"• {WORKFLOWS[k].label}" for k in agent.workflow_keys if k in WORKFLOWS
        )
        self.query_one("#ap-agent-tasks-label", Static).update("tasks owned:" if tasks else "")
        self.query_one("#ap-agent-tasks", Static).update(tasks)

    def _set_active(self, idx: int) -> None:
        idx = max(0, min(len(self._cards) - 1, idx))
        self._cards[self._selected_idx].remove_class("-active")
        self._selected_idx = idx
        self._cards[idx].add_class("-active")
        self._cards[idx].remove_class("-hover")
        self._hovered_card_idx = None
        self._update_sidebar(self._agents[idx])

    def _find_agent_card(self, widget) -> _AgentCard | None:
        """Walk up the widget tree to find an _AgentCard ancestor."""
        current = widget
        while current is not None:
            if isinstance(current, _AgentCard):
                return current
            current = getattr(current, "parent", None)
        return None

    def _set_card_hover(self, idx: int | None) -> None:
        prev = self._hovered_card_idx
        if prev == idx:
            return
        if prev is not None and 0 <= prev < len(self._cards):
            self._cards[prev].remove_class("-hover")
        self._hovered_card_idx = idx
        if idx is not None and 0 <= idx < len(self._cards):
            card = self._cards[idx]
            if not card.has_class("-active"):
                card.add_class("-hover")
            self._update_sidebar(self._agents[idx])

    def _set_ap_tab_hover(self, tab: Static | None) -> None:
        prev = self._hovered_ap_tab
        if prev is tab:
            return
        if prev is not None:
            prev.remove_class("-hover")
        self._hovered_ap_tab = tab
        if tab is not None and "-active" not in tab.classes:
            tab.add_class("-hover")

    def on_mouse_move(self, event: events.MouseMove) -> None:
        widget = event.widget
        if isinstance(widget, Static) and "ap-tab-chip" in widget.classes:
            self._set_ap_tab_hover(widget)
            self._set_card_hover(None)
            return
        self._set_ap_tab_hover(None)
        card = self._find_agent_card(widget)
        if card is not None:
            idx = next((i for i, c in enumerate(self._cards) if c is card), None)
            self._set_card_hover(idx)
        else:
            self._set_card_hover(None)

    def on_mouse_leave(self, event: events.MouseLeave) -> None:
        self._set_ap_tab_hover(None)
        self._set_card_hover(None)

    def on__agent_card_selected(self, event: _AgentCard.Selected) -> None:
        idx = next((i for i, c in enumerate(self._cards) if c._agent is event.agent), None)
        if idx is not None:
            if idx == self._selected_idx:
                # Second click on already-selected card → confirm (same as Enter)
                self.action_confirm()
            else:
                self._set_active(idx)

    def action_move_left(self) -> None:
        self._set_active(self._selected_idx - 1)

    def action_move_right(self) -> None:
        self._set_active(self._selected_idx + 1)

    def action_move_up(self) -> None:
        self._set_active(self._selected_idx - 5)

    def action_move_down(self) -> None:
        self._set_active(self._selected_idx + 5)

    def action_cycle_model(self) -> None:
        picker = self.query_one(_ModelPicker)
        models = list(Model)
        picker.set_model(models[(models.index(picker.model) + 1) % len(models)])

    def action_confirm(self) -> None:
        agent = self._agents[self._selected_idx]
        model = self.query_one(_ModelPicker).model
        self._pending_agent = agent
        self.app.push_screen(
            WorkflowPickerModal(agent=agent, initial_model=model),
            self._on_workflow_result,
        )

    def _on_workflow_result(self, result: "tuple | None") -> None:
        """Handle WorkflowPickerModal dismissal. If cancelled, stay on this screen (scroll preserved)."""
        if result is None:
            return
        wf_key, model = result
        self.dismiss((self._pending_agent, wf_key, model))

    def action_close(self) -> None:
        self.dismiss(None)

    def on_click(self, event: events.Click) -> None:
        node_id = getattr(event.widget, "id", None) or ""
        if node_id == "ap-tab-sprint":
            self.dismiss(("__nav__", "sprint"))
        elif node_id == "ap-tab-history":
            self.dismiss(("__nav__", "history"))


def _set_story_status(sprint_status_path: Path, story_id: str, new_status: str, md_path: "Path | None" = None) -> None:
    """Update a single story's status in sprint-status.yaml and, when available, in the story .md file."""
    import re
    # Replace only the matching status line so comments and spacing survive.
    text = sprint_status_path.read_text(encoding="utf-8")
    escaped_id = re.escape(story_id)
    updated = re.sub(
        rf"(?m)^(\s*{escaped_id}\s*:\s*).*$",
        rf"\g<1>{new_status}",
        text,
        count=1,
    )
    sprint_status_path.write_text(updated, encoding="utf-8")
    if md_path and Path(md_path).exists():
        text = Path(md_path).read_text(encoding="utf-8")
        # Match both "Status: <value>" and "**Status:** <value>"
        updated = re.sub(r"(?m)^(\*\*Status:\*\*\s*|Status:\s*).*$", rf"\g<1>{new_status}", text, count=1)
        if updated != text:
            Path(md_path).write_text(updated, encoding="utf-8")


class _StatusOption(Widget):
    """A selectable status option in an inline status dropdown."""

    class Selected(Message):
        def __init__(self, status: StoryStatus) -> None:
            super().__init__()
            self.status = status

    def __init__(self, status: StoryStatus, current: bool) -> None:
        super().__init__(classes=f"status-opt {'-current' if current else ''} sdo-{status.value}".strip())
        self._status = status

    def compose(self) -> ComposeResult:
        marker = "◀" if self.has_class("-current") else " "
        yield Static(f"{marker} {self._status.emoji} {self._status.value}", classes="status-opt-label")

    def on_click(self) -> None:
        self.post_message(self.Selected(self._status))


class StatusDropdownOverlay(ModalScreen):
    """Floating overlay for picking a story status, anchored below the invoking widget."""

    CSS = """
    StatusDropdownOverlay {
        align: left top;
        background: rgba(0,0,0,0);
    }

    #sdo-outer {
        width: 30;
        height: auto;
        background: #0F172A;
        border: round #1E293B;
        padding: 0 0;
    }

    #sdo-header {
        height: 1;
        background: #1E293B;
        padding: 0 2;
    }

    #sdo-header-label {
        color: #64748B;
        content-align: left middle;
    }

    .status-opt {
        height: 2;
        width: 1fr;
        padding: 0 2;
        align: left middle;
    }

    .status-opt.-current {
        background: #1E293B;
    }

    .status-opt:hover {
        background: #172033;
    }

    .status-opt-label {
        color: #E5E7EB;
        content-align: left middle;
    }

    .sdo-ready-for-dev .status-opt-label { color: #22C55E; }
    .sdo-in-progress   .status-opt-label { color: #8BE9FD; }
    .sdo-review        .status-opt-label { color: #C084FC; }
    .sdo-done          .status-opt-label { color: #22C55E; }
    .sdo-backlog       .status-opt-label { color: #F59E0B; }
    .sdo-blocked       .status-opt-label { color: #ff5555; }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close", "Close", show=False),
    ]

    _STATUSES = [
        StoryStatus.READY_FOR_DEV,
        StoryStatus.IN_PROGRESS,
        StoryStatus.REVIEW,
        StoryStatus.DONE,
        StoryStatus.BACKLOG,
        StoryStatus.BLOCKED,
    ]

    def __init__(self, current: StoryStatus, anchor: tuple[int, int, int, int] = (0, 0, 30, 3)) -> None:
        super().__init__()
        self._current = current
        # anchor = (x, y, width, height) in screen cells
        self._anchor = anchor

    def compose(self) -> ComposeResult:
        with Container(id="sdo-outer"):
            yield Static("change status", id="sdo-header-label", classes="")
            for s in self._STATUSES:
                yield _StatusOption(s, current=(s == self._current))

    def on_mount(self) -> None:
        ax, ay, aw, ah = self._anchor
        outer = self.query_one("#sdo-outer")
        # Position dropdown below the anchor chip; clamp left edge to anchor x
        outer.styles.offset = (ax, ay + ah)
        # Match width at least to anchor width for visual continuity
        outer.styles.width = max(30, aw)

    def on__status_option_selected(self, event: _StatusOption.Selected) -> None:
        self.dismiss(event.status)

    def action_close(self) -> None:
        self.dismiss(None)

    def on_click(self, event: events.Click) -> None:
        if event.widget is self:
            self.dismiss(None)


# ---------------------------------------------------------------------------
# Filter ordering (TUI-8 / TUI-16)
# ---------------------------------------------------------------------------
_FILTERS: list[str | None] = [
    None,             # 0 — All
    "ready-for-dev",  # 1
    "in-progress",    # 2
    "review",         # 3
    "blocked",        # 4
    "done",           # 5  (direct key)
    "backlog",        # 6
]

FILTER_LABELS: list[tuple[str | None, str, str]] = [
    (None,            "All",         "0"),
    ("ready-for-dev", "Ready",       "f"),
    ("in-progress",   "In Progress", "f"),
    ("review",        "Review",      "f"),
    ("blocked",       "Blocked",     "f"),
    ("done",          "Done",        "5"),
    ("backlog",       "Backlog",     "6"),
]


def _status_badge(yaml_status: str) -> str:
    """Return Rich-markup badge for a raw yaml_status string (TUI-17)."""
    try:
        return STATUS_BADGES[StoryStatus(yaml_status)]
    except (ValueError, KeyError):
        return f"[#6272a4]{yaml_status}[/]"


def _status_text(yaml_status: str) -> str:
    """Return plain icon + label for a status — CSS class provides the color."""
    try:
        s = StoryStatus(yaml_status)
        return f"{s.emoji} {s.value}"
    except ValueError:
        return f"? {yaml_status}"


_STATUS_BG = {
    "ready-for-dev": ("#22C55E", "#0D2318"),
    "done":          ("#22C55E", "#0D2318"),
    "in-progress":   ("#8BE9FD", "#071E26"),
    "review":        ("#C084FC", "#1A0D2B"),
    "backlog":       ("#F59E0B", "#261A04"),
    "blocked":       ("#FF5555", "#260A0A"),
}


class _CardStatusBlock(Static):
    """Plain bold status label, coloured, anchored bottom-right in the card."""

    DEFAULT_CSS = """
    _CardStatusBlock {
        width: auto;
        height: 1;
        padding: 0 1;
        content-align: right middle;
    }
    """

    def __init__(self, yaml_status: str) -> None:
        fg = _STATUS_BG.get(yaml_status, ("#E5E7EB", "#000"))[0]
        label = _status_text(yaml_status)
        super().__init__(f"[bold {fg}]{label}[/]", classes="card-status-block")
        self._yaml_status = yaml_status

    def _update_status(self, yaml_status: str) -> None:
        self._yaml_status = yaml_status
        fg = _STATUS_BG.get(yaml_status, ("#E5E7EB", "#000"))[0]
        label = _status_text(yaml_status)
        self.update(f"[bold {fg}]{label}[/]")


# ---------------------------------------------------------------------------
# Story preview placeholder (TUI-5 / TUI-13)
# ---------------------------------------------------------------------------
_STORY_PREVIEW_PLACEHOLDER = (
    "## No story file yet\n\n"
    "Run **Create Story** first to generate the story document."
)


class StoryPreviewScreen(ModalScreen["Story | None"]):
    """Full-screen markdown preview of a story file (TUI-5)."""

    BINDINGS = [
        Binding("escape", "close_preview", "Close", show=False),
        Binding("enter", "open_actions", "Actions", show=False),
        Binding("space", "close_preview", "Close", show=False),
    ]

    CSS = """
    StoryPreviewScreen {
        align: center middle;
    }
    #preview-box {
        width: 90%;
        height: 90%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
        overflow-y: auto;
    }
    #preview-title {
        margin-bottom: 1;
        color: $text;
    }
    #preview-hint {
        margin-top: 1;
        color: $text-muted;
    }
    """

    def __init__(self, story: "Story") -> None:
        super().__init__()
        self._story = story

    def compose(self) -> ComposeResult:
        content = _STORY_PREVIEW_PLACEHOLDER
        if self._story.file_path and Path(self._story.file_path).exists():
            try:
                content = Path(self._story.file_path).read_text(encoding="utf-8")
            except OSError:
                pass
        with Container(id="preview-box"):
            yield Static(
                f"[bold]{self._story.id}[/]  [dim]{self._story.title[:60]}[/dim]",
                id="preview-title",
            )
            yield Markdown(content, id="preview-md")
            yield Static("[dim]Esc/Space close  Enter open actions[/dim]", id="preview-hint")

    def action_close_preview(self) -> None:
        self.dismiss(None)

    def action_open_actions(self) -> None:
        self.dismiss(self._story)

    def on_click(self, event: events.Click) -> None:  # type: ignore[override]
        if event.widget is self:
            self.dismiss(None)


class _DashboardHistoryRow(Widget):
    """Row widget for in-page history tab content."""

    class Highlighted(Message):
        """Posted on single-click to select/highlight the row without running."""
        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    class Selected(Message):
        """Posted on double-click to open/run the history entry."""
        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    def __init__(self, entry: HistoryEntry, index: int, active: bool = False) -> None:
        super().__init__(classes="history-log-row" + (" -active" if active else ""))
        self._entry = entry
        self._index = index

    def compose(self) -> ComposeResult:
        wf_def = WORKFLOWS.get(self._entry.workflow)
        wf_str = wf_def.label if wf_def else self._entry.workflow or "unknown workflow"
        icon = "↩ resume" if self._entry.session_id else "▶ re-run"
        task = self._entry.task_name or self._entry.story_id or "—"
        if self._entry.branch:
            branch = self._entry.branch
        elif self._entry.story_id:
            branch = f"feature/{self._entry.story_id} (inferred)"
        else:
            branch = "(not captured)"
        usage = self._entry.usage_est or "n/a"
        api_time = self._entry.api_time or "n/a"
        session_time = self._entry.session_time or "n/a"
        code_changes = self._entry.code_changes or "n/a"

        if task != "—":
            yield Static(f"task: {task}", classes="history-log-task")
        yield Static(f"workflow: {wf_str}", classes="history-log-workflow")
        yield Static(f"branch worked: {branch}", classes="history-log-branch")
        yield Static(
            f"Total usage est: {usage} | API time spent: {api_time}",
            classes="history-log-stats",
        )
        yield Static(
            f"Total session time: {session_time} | Total code changes: {code_changes}",
            classes="history-log-stats",
        )
        yield Static(f"{icon}   {self._entry.ts}   {self._entry.model}", classes="history-log-meta")

    def on_click(self, event: events.Click) -> None:
        if event.chain >= 2:
            self.post_message(self.Selected(self._index))
        else:
            self.post_message(self.Highlighted(self._index))

    def on_mouse_enter(self) -> None:
        self.add_class("-hover")

    def on_mouse_leave(self) -> None:
        self.remove_class("-hover")


# ---------------------------------------------------------------------------
# Workflow history screen (TUI-6) — interactive restore
# ---------------------------------------------------------------------------
class _GlobalHistoryRow(Widget):
    """A selectable row in the global history screen."""

    class Highlighted(Message):
        """Posted on single-click to highlight/select the row without running."""
        def __init__(self, entry: HistoryEntry) -> None:
            super().__init__()
            self.entry = entry

    class Selected(Message):
        """Posted on double-click to open/run the history entry."""
        def __init__(self, entry: HistoryEntry) -> None:
            super().__init__()
            self.entry = entry

    def __init__(self, entry: HistoryEntry, active: bool = False) -> None:
        super().__init__(classes="gh-row" + (" -active" if active else ""))
        self._entry = entry

    def compose(self) -> ComposeResult:
        icon = "↩ resume" if self._entry.session_id else "▶ re-run"
        wf_def = WORKFLOWS.get(self._entry.workflow)
        wf_str = wf_def.label if wf_def else self._entry.workflow or "unknown workflow"
        task = self._entry.task_name or self._entry.story_id or "—"
        branch = self._entry.branch or "(unknown)"
        usage = self._entry.usage_est or "n/a"
        api_time = self._entry.api_time or "n/a"
        session_time = self._entry.session_time or "n/a"
        code_changes = self._entry.code_changes or "n/a"

        if task != "—":
            yield Static(f"task: {task}", classes="gh-row-task")
        yield Static(f"workflow: {wf_str}", classes="gh-row-workflow")
        yield Static(f"branch worked: {branch}", classes="gh-row-branch")
        yield Static(
            f"Total usage est: {usage} | API time spent: {api_time}",
            classes="gh-row-stats",
        )
        yield Static(
            f"Total session time: {session_time} | Total code changes: {code_changes}",
            classes="gh-row-stats",
        )
        yield Static(f"{icon}   {self._entry.ts}   {self._entry.model}", classes="gh-row-meta")

    def on_click(self, event: events.Click) -> None:
        if event.chain >= 2:
            self.post_message(self.Selected(self._entry))
        else:
            self.post_message(self.Highlighted(self._entry))

    def on_mouse_enter(self) -> None:
        self.add_class("-hover")

    def on_mouse_leave(self) -> None:
        self.remove_class("-hover")


class _NameSessionModal(ModalScreen["str | None"]):
    """Lightweight post-run prompt — lets the user label a history entry or skip."""

    BINDINGS = [
        Binding("escape", "skip", "Skip", show=False),
    ]

    CSS = """
    _NameSessionModal {
        align: center middle;
    }
    #name-session-box {
        width: 72;
        height: auto;
        background: #0B1220;
        border: round #374151;
        padding: 1 2;
    }
    #name-session-title {
        color: #93C5FD;
        text-style: bold;
        margin-bottom: 1;
    }
    #name-session-input {
        width: 1fr;
        background: #111827;
        border: tall #374151;
        color: #E5E7EB;
        margin-bottom: 1;
    }
    #name-session-input:focus {
        border: tall #93C5FD;
    }
    #name-session-hint {
        color: #64748B;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(id="name-session-box"):
            yield Static("name this session for history", id="name-session-title")
            yield Input(placeholder="e.g. investigate auth refactor", id="name-session-input")
            yield Static("enter to save  •  esc to skip", id="name-session-hint")

    def on_mount(self) -> None:
        self.query_one("#name-session-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        self.dismiss(name if name else None)

    def action_skip(self) -> None:
        self.dismiss(None)


class HistoryScreen(ModalScreen["HistoryEntry | None"]):
    """Interactive workflow run history — select an entry to resume or re-run it."""

    BINDINGS = [
        Binding("escape", "action_close", "Close", show=False),
        Binding("q", "action_close", "Close", show=False),
        Binding("h", "action_close", "Close", show=False),
        Binding("up", "prev_row", "Prev", show=False),
        Binding("down", "next_row", "Next", show=False),
        Binding("enter", "restore", "Restore", show=False),
    ]

    CSS = """
    HistoryScreen {
        align: center middle;
    }
    #history-box {
        width: 150;
        height: auto;
        max-height: 46;
        border: round #111111;
        background: #0C0C0C;
        padding: 1 1;
        overflow-y: auto;
    }
    #history-title {
        color: #E5E5E5;
        text-style: bold;
        margin-bottom: 1;
    }
    #history-list {
        height: auto;
    }
    #history-empty {
        color: #6B7280;
    }
    .gh-row {
        layout: vertical;
        height: auto;
        padding: 0 1;
        margin-bottom: 1;
        background: #171717;
        border: round #171717;
    }
    .gh-row.-active {
        background: #172033;
        border: round #172033;
    }
    .gh-row.-hover {
        background: #1F2937;
        border: round #1F2937;
    }
    .gh-row-task {
        color: #E5E5E5;
        text-style: bold;
    }
    .gh-row-workflow {
        color: #818CF8;
    }
    .gh-row-branch {
        color: #22C55E;
    }
    .gh-row-meta {
        color: #6B7280;
    }
    .gh-row-stats {
        color: #A3A3A3;
    }
    #history-hint {
        margin-top: 1;
        color: #64748B;
    }
    """

    def __init__(self, project_root: Path) -> None:
        super().__init__()
        self._project_root = project_root
        self._entries: list[HistoryEntry] = []
        self._selected_idx: int = 0

    def compose(self) -> ComposeResult:
        entries = load_history(self._project_root)
        self._entries = list(reversed(entries))  # newest first
        with Container(id="history-box"):
            yield Static("> history log (all entries)", id="history-title")
            with Container(id="history-list"):
                if not self._entries:
                    yield Static("No history yet.", id="history-empty")
                else:
                    for i, e in enumerate(self._entries):
                        yield _GlobalHistoryRow(e, active=(i == 0))
            yield Static(
                "[dim]↑↓ navigate  Enter/double-click open  Esc close[/dim]",
                id="history-hint",
            )

    def _set_active(self, idx: int) -> None:
        rows = list(self.query(_GlobalHistoryRow))
        for i, row in enumerate(rows):
            row.set_class(i == idx, "-active")
        self._selected_idx = idx
        if 0 <= idx < len(rows):
            rows[idx].scroll_visible()

    def action_prev_row(self) -> None:
        self._set_active(max(0, self._selected_idx - 1))

    def action_next_row(self) -> None:
        self._set_active(min(len(self._entries) - 1, self._selected_idx + 1))

    def action_restore(self) -> None:
        if self._entries:
            self.dismiss(self._entries[self._selected_idx])

    def action_close(self) -> None:
        self.dismiss(None)

    def on__global_history_row_highlighted(self, message: _GlobalHistoryRow.Highlighted) -> None:
        idx = next((i for i, e in enumerate(self._entries) if e is message.entry), None)
        if idx is not None:
            self._set_active(idx)

    def on__global_history_row_selected(self, message: _GlobalHistoryRow.Selected) -> None:
        self.dismiss(message.entry)

    def on_click(self, event: events.Click) -> None:  # type: ignore[override]
        if event.widget is self:
            self.dismiss(None)


# ---------------------------------------------------------------------------
# Help screen (TUI-15)
# ---------------------------------------------------------------------------
_HELP_TEXT = """\
## BMAD TUI — Keyboard Reference

| Key | Action |
|-----|--------|
| `r` | Refresh state from disk |
| `Enter` | Open action modal for selected story |
| `Space` | Preview selected story markdown |
| `/` | Search stories, agents, workflows, and history |
| `a` | Open agent launcher |
| `w` | Open workflow picker |
| `h` | Workflow run history |
| `f` | Cycle status filter |
| `0` | Clear filter (show All) |
| `5` | Filter: done |
| `6` | Filter: backlog |
| `m` | Cycle model |
| `s` | Launch sprint-planning workflow |
| `q` | Quit |

### Navigation
| Key | Action |
|-----|--------|
| `↑ ↓ ← →` | Navigate story cards |
| `Click` | Select story / sprint |
| `Right-click` | Change story status |
"""


class HelpScreen(ModalScreen[None]):
    """Keyboard shortcut reference (TUI-15)."""

    BINDINGS = [
        Binding("escape", "dismiss(None)", "Close", show=False),
        Binding("q", "dismiss(None)", "Close", show=False),
        Binding("question_mark", "dismiss(None)", "Close", show=False),
    ]

    CSS = """
    HelpScreen {
        align: center middle;
    }
    #help-box {
        width: 72;
        height: auto;
        max-height: 45;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
        overflow-y: auto;
    }
    #help-hint {
        margin-top: 1;
        color: $text-muted;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(id="help-box"):
            yield Markdown(_HELP_TEXT, id="help-md")
            yield Static("[dim]Esc / q / ? — close[/dim]", id="help-hint")

    def on_click(self, event: events.Click) -> None:  # type: ignore[override]
        if event.widget is self:
            self.dismiss(None)


# ---------------------------------------------------------------------------
# Search screen (press / from main view)
# ---------------------------------------------------------------------------

class _SearchResultRow(Widget):
    """Single result row in the search modal."""

    class Selected(Message):
        def __init__(self, result: tuple[str, str, str]) -> None:
            super().__init__()
            self.result = result

    DEFAULT_CSS = """
    _SearchResultRow {
        height: 3;
        padding: 0 1;
        background: #111827;
        border: round #111827;
        margin-bottom: 1;
        layout: horizontal;
    }
    _SearchResultRow.-active {
        background: #233047;
        border: round #233047;
    }
    _SearchResultRow .sr-label {
        width: 1fr;
        content-align: left middle;
        color: #CBD5E1;
    }
    _SearchResultRow.-active .sr-label {
        color: #F8FAFC;
        text-style: bold;
    }
    _SearchResultRow .sr-kind {
        width: auto;
        content-align: right middle;
        color: #64748B;
    }
    _SearchResultRow.-active .sr-kind {
        color: #94A3B8;
    }
    """

    def __init__(self, result: tuple[str, str, str], active: bool = False) -> None:
        super().__init__()
        self._result = result
        if active:
            self.add_class("-active")

    def compose(self) -> ComposeResult:
        kind, _key, label = self._result
        yield Static(label, classes="sr-label")
        yield Static(kind, classes="sr-kind")

    def on_click(self, event: events.Click) -> None:
        self.post_message(self.Selected(self._result))


class SearchScreen(ModalScreen):
    """Global search — stories, agents, workflows, and history. Press / to open."""

    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("up", "nav_up", "Up", show=False),
        Binding("down", "nav_down", "Down", show=False),
    ]

    CSS = """
    SearchScreen {
        align: center middle;
    }
    #search-box {
        width: 120;
        height: auto;
        max-height: 50;
        background: #0B1220;
        border: round #0B1220;
        padding: 1 2;
    }
    #search-header {
        height: 3;
        margin-bottom: 1;
    }
    #search-title {
        width: 1fr;
        color: #E5E7EB;
        text-style: bold;
        content-align: left middle;
    }
    #search-close {
        width: auto;
        background: #1F2937;
        border: round #1F2937;
        color: #E5E7EB;
        padding: 0 1;
        content-align: center middle;
        height: 3;
    }
    #search-input {
        width: 1fr;
        background: #111827;
        border: tall #374151;
        color: #E5E7EB;
        margin-bottom: 1;
    }
    #search-input:focus {
        border: tall #93C5FD;
    }
    #search-results {
        height: auto;
        max-height: 30;
        overflow-y: auto;
    }
    .search-empty {
        color: #64748B;
        padding: 0 1;
    }
    #search-hint {
        color: #64748B;
        margin-top: 1;
    }
    """

    def __init__(
        self,
        stories: list[Story],
        history_entries: list[HistoryEntry] | None = None,
        agents: "list[AgentDef] | None" = None,
    ) -> None:
        super().__init__()
        self._all_stories = stories
        self._all_history: list[HistoryEntry] = history_entries or []
        self._all_agents: list[AgentDef] = agents if agents is not None else list(AGENTS)
        self._results: list[tuple[str, str, str]] = []
        self._selected_idx: int = 0
        self._row_widgets: list[_SearchResultRow] = []

    def compose(self) -> ComposeResult:
        with Container(id="search-box"):
            with Horizontal(id="search-header"):
                yield Static("/ search", id="search-title")
                yield Static("esc ✕", id="search-close")
            yield Input(placeholder="type to search stories, agents, workflows, history…", id="search-input")
            yield Container(id="search-results")
            yield Static("↑/↓ navigate   enter select   esc close", id="search-hint")

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()
        self._rebuild_results("")

    def _normalize(self, text: str) -> str:
        """Normalize text for fuzzy matching: treat . and _ as -."""
        return text.replace(".", "-").replace("_", "-").lower()

    def _build_result_list(self, query: str) -> list[tuple[str, str, str]]:
        q = self._normalize(query.strip())
        results: list[tuple[str, str, str]] = []
        for story in self._all_stories:
            if not story.id or story.id == "_" or not story.title or not story.title.strip():
                continue
            haystack = self._normalize(f"{story.id} {story.title} {story.yaml_status}")
            if not q or q in haystack:
                badge = STATUS_BADGES.get(story.yaml_status, "")
                results.append(("story", story.id, f"{badge} {story.id} — {story.title}"))
        for entry in self._all_history:
            if not entry.session_id:
                continue
            ts_short = entry.ts[:10] if len(entry.ts) >= 10 else entry.ts
            display = entry.task_name or entry.story_id or entry.workflow
            label = f"{ts_short} — {display} [{entry.workflow}]"
            haystack = self._normalize(f"{entry.ts} {entry.story_id} {entry.task_name} {entry.workflow} {entry.branch}")
            if not q or q in haystack:
                results.append(("history", entry.session_id, label))
        for agent in sorted(self._all_agents, key=lambda a: a.name):
            haystack = self._normalize(f"{agent.name} {agent.persona}")
            if not q or q in haystack:
                results.append(("agent", agent.name, agent.persona))
        for key, wf in sorted(WORKFLOWS.items(), key=lambda x: x[1].label):
            haystack = self._normalize(f"{key} {wf.label}")
            if not q or q in haystack:
                results.append(("workflow", key, wf.label))
        return results[:60]

    def _rebuild_results(self, query: str) -> None:
        container = self.query_one("#search-results")
        container.remove_children()
        self._results = self._build_result_list(query)
        self._selected_idx = 0
        self._row_widgets = []
        if not self._results:
            container.mount(Static("no results", classes="search-empty"))
            return
        for i, result in enumerate(self._results):
            row = _SearchResultRow(result, active=(i == 0))
            container.mount(row)
            self._row_widgets.append(row)

    def on_input_changed(self, event: Input.Changed) -> None:
        self._rebuild_results(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._confirm()

    def _set_active(self, idx: int) -> None:
        if not self._row_widgets:
            return
        idx = max(0, min(len(self._row_widgets) - 1, idx))
        if 0 <= self._selected_idx < len(self._row_widgets):
            self._row_widgets[self._selected_idx].remove_class("-active")
        self._selected_idx = idx
        self._row_widgets[idx].add_class("-active")
        self._row_widgets[idx].scroll_visible()

    def action_nav_up(self) -> None:
        self._set_active(self._selected_idx - 1)

    def action_nav_down(self) -> None:
        self._set_active(self._selected_idx + 1)

    def _confirm(self) -> None:
        if self._results and 0 <= self._selected_idx < len(self._results):
            self.dismiss(self._results[self._selected_idx])
        else:
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)

    def on__search_result_row_selected(self, message: _SearchResultRow.Selected) -> None:
        self.dismiss(message.result)

    def on_click(self, event: events.Click) -> None:  # type: ignore[override]
        node_id = getattr(event.widget, "id", None) or ""
        if event.widget is self or node_id == "search-close":
            self.dismiss(None)


def _parse_open_subtasks(file_path) -> tuple[list[str], int]:
    """Return (open_tasks, done_count) from a story .md Tasks section.

    Parses both top-level (- [ ]) and indented (  - [ ]) task lines.
    """
    if file_path is None:
        return [], 0
    try:
        text = Path(file_path).read_text()
    except OSError:
        return [], 0

    in_section = False
    open_tasks: list[str] = []
    done_count = 0
    for line in text.splitlines():
        if re.match(r"^##\s+Tasks", line, re.IGNORECASE):
            in_section = True
            continue
        if in_section and re.match(r"^##\s+", line):
            break
        if not in_section:
            continue
        m = re.match(r"^\s*- \[([ xX])\] (.+)", line)
        if m:
            checked = m.group(1).lower() == "x"
            if checked:
                done_count += 1
            else:
                open_tasks.append(m.group(2).strip())
    return open_tasks, done_count


def _story_sort_key(story: Story) -> tuple[int, int, str]:
    parts = story.id.split("-")
    epic_num = int(parts[0]) if parts[0].isdigit() else 0
    if len(parts) < 2:
        return (epic_num, 0, "")
    num_match = re.match(r"(\d+)", parts[1])
    num = int(num_match.group(1)) if num_match else 0
    suffix = parts[1][num_match.end() :] if num_match else parts[1]
    return (epic_num, num, suffix)


class FilterPickerModal(ModalScreen):
    """Filter picker modal — navigate up/down and press enter to apply a filter."""

    CSS = """
    FilterPickerModal {
        align: center middle;
    }

    #fp-outer {
        width: 54;
        height: auto;
        background: #0B1220;
        border: round #0B1220;
        padding: 1 2;
    }

    #fp-header {
        height: 3;
        margin-bottom: 1;
    }

    #fp-title {
        width: 1fr;
        color: #E5E7EB;
        text-style: bold;
        content-align: left middle;
    }

    #fp-close {
        width: auto;
        background: #1F2937;
        border: round #1F2937;
        color: #E5E7EB;
        padding: 0 1;
        content-align: center middle;
        height: 3;
    }

    #fp-sub {
        color: #94A3B8;
        margin-bottom: 1;
    }

    .fp-option {
        height: 3;
        width: 1fr;
        background: #111827;
        border: round #111827;
        padding: 0 2;
        margin-bottom: 1;
        align: left middle;
    }

    .fp-option.-active {
        background: #233047;
        border: round #233047;
    }

    .fp-option-label {
        width: 1fr;
        content-align: left middle;
        color: #CBD5E1;
    }

    .fp-option.-active .fp-option-label {
        color: #F8FAFC;
        text-style: bold;
    }

    .fp-option-count {
        width: auto;
        content-align: right middle;
        color: #64748B;
    }

    .fp-option.-active .fp-option-count {
        color: #94A3B8;
    }

    #fp-hint {
        color: #64748B;
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close", "Close", show=False),
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("enter", "confirm", "Confirm", show=False),
    ]

    def __init__(self, current_index: int, counts: list[int]) -> None:
        super().__init__()
        self._selected_idx = current_index
        self._counts = counts
        self._options: list[Widget] = []

    def compose(self) -> ComposeResult:
        with Container(id="fp-outer"):
            with Horizontal(id="fp-header"):
                yield Static("filter stories", id="fp-title")
                yield Static("esc ✕", id="fp-close")
            yield Static("select a filter and press enter", id="fp-sub")
            for i, (_, label, _key) in enumerate(FILTER_LABELS):
                classes = "fp-option" + (" -active" if i == self._selected_idx else "")
                with Horizontal(classes=classes):
                    yield Static(label, classes="fp-option-label")
                    yield Static(str(self._counts[i]), classes="fp-option-count")
            yield Static("↑/↓ move   enter apply   esc close", id="fp-hint")

    def on_mount(self) -> None:
        self._options = list(self.query(".fp-option"))

    def _set_active(self, idx: int) -> None:
        idx = max(0, min(len(self._options) - 1, idx))
        if idx == self._selected_idx:
            return
        self._options[self._selected_idx].remove_class("-active")
        self._selected_idx = idx
        self._options[idx].add_class("-active")

    def action_move_up(self) -> None:
        self._set_active(self._selected_idx - 1)

    def action_move_down(self) -> None:
        self._set_active(self._selected_idx + 1)

    def action_confirm(self) -> None:
        self.dismiss(self._selected_idx)

    def action_close(self) -> None:
        self.dismiss(None)

    def on_click(self, event: events.Click) -> None:
        if event.widget is self:
            self.action_close()
            return
        node_id = getattr(event.widget, "id", None) or ""
        if node_id == "fp-close":
            self.action_close()
            return
        current = event.widget
        while current is not None:
            if current in self._options:
                self._set_active(self._options.index(current))
                self.action_confirm()
                return
            current = getattr(current, "parent", None)


class CliPickerModal(ModalScreen):
    """CLI picker modal — choose between installed CLI tools (copilot / claude)."""

    CSS = """
    CliPickerModal {
        align: center middle;
    }

    #cp-outer {
        width: 54;
        height: auto;
        background: #0B1220;
        border: round #0B1220;
        padding: 1 2;
    }

    #cp-header {
        height: 3;
        margin-bottom: 1;
    }

    #cp-title {
        width: 1fr;
        color: #E5E7EB;
        text-style: bold;
        content-align: left middle;
    }

    #cp-close {
        width: auto;
        background: #1F2937;
        border: round #1F2937;
        color: #E5E7EB;
        padding: 0 1;
        content-align: center middle;
        height: 3;
    }

    #cp-sub {
        color: #94A3B8;
        margin-bottom: 1;
    }

    .cp-option {
        height: 3;
        width: 1fr;
        background: #111827;
        border: round #111827;
        padding: 0 2;
        margin-bottom: 1;
        align: left middle;
    }

    .cp-option.-active {
        background: #233047;
        border: round #233047;
    }

    .cp-option-label {
        width: 1fr;
        content-align: left middle;
        color: #CBD5E1;
    }

    .cp-option.-active .cp-option-label {
        color: #F8FAFC;
        text-style: bold;
    }

    #cp-hint {
        color: #64748B;
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close", "Close", show=False),
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("enter", "confirm", "Confirm", show=False),
    ]

    def __init__(self, current_cli: str, installed_clis: list[str]) -> None:
        super().__init__()
        self._installed = installed_clis
        self._selected_idx = self._installed.index(current_cli) if current_cli in self._installed else 0
        self._options: list[Widget] = []

    def compose(self) -> ComposeResult:
        _LABELS = {"copilot": "GitHub Copilot", "claude": "Claude (Anthropic)"}
        with Container(id="cp-outer"):
            with Horizontal(id="cp-header"):
                yield Static("select CLI", id="cp-title")
                yield Static("esc ✕", id="cp-close")
            yield Static("choose which CLI to use for agent sessions", id="cp-sub")
            for i, cli in enumerate(self._installed):
                classes = "cp-option" + (" -active" if i == self._selected_idx else "")
                with Horizontal(classes=classes):
                    yield Static(_LABELS.get(cli, cli), classes="cp-option-label")
            yield Static("↑/↓ move   enter select   esc close", id="cp-hint")

    def on_mount(self) -> None:
        self._options = list(self.query(".cp-option"))

    def _set_active(self, idx: int) -> None:
        idx = max(0, min(len(self._options) - 1, idx))
        if idx == self._selected_idx:
            return
        self._options[self._selected_idx].remove_class("-active")
        self._selected_idx = idx
        self._options[idx].add_class("-active")

    def action_move_up(self) -> None:
        self._set_active(self._selected_idx - 1)

    def action_move_down(self) -> None:
        self._set_active(self._selected_idx + 1)

    def action_confirm(self) -> None:
        self.dismiss(self._installed[self._selected_idx])

    def action_close(self) -> None:
        self.dismiss(None)

    def on_click(self, event: events.Click) -> None:
        if event.widget is self:
            self.action_close()
            return
        node_id = getattr(event.widget, "id", None) or ""
        if node_id == "cp-close":
            self.action_close()
            return
        current = event.widget
        while current is not None:
            if current in self._options:
                self._set_active(self._options.index(current))
                self.action_confirm()
                return
            current = getattr(current, "parent", None)


class Dashboard(App):
    TITLE = "BMAD Home"
    SUB_TITLE = ""

    CSS = """
    Screen {
        background: #0C0C0C;
        color: #E5E7EB;
    }

    #root {
        layout: vertical;
        padding: 1;
        height: 1fr;
        width: 1fr;
    }

    #header {
        height: 5;
        background: #111111;
        border: round #111111;
        padding: 0 1;
    }

    #header-title {
        width: auto;
        color: #22C55E;
        text-style: bold;
        content-align: left middle;
        margin-right: 2;
    }

    #header-left {
        width: auto;
        height: 1fr;
        layout: vertical;
        margin-right: 2;
    }

    #header-branch {
        width: auto;
        color: #6B7280;
        content-align: left middle;
    }

    #header-tabs-area {
        width: 1fr;
        height: 1fr;
        layout: horizontal;
    }

    .header-fill {
        width: 1fr;
        height: 1fr;
    }

    #header-tabs {
        width: auto;
        height: 1fr;
    }

    .tab-chip {
        background: #111111;
        color: #9CA3AF;
        padding: 0 2;
        margin: 0 1;
        height: 1fr;
        width: auto;
        content-align: center middle;
    }

    .tab-chip.-active {
        background: #172033;
        color: #E5E7EB;
        text-style: bold;
    }

    .tab-chip.-hover {
        background: #1F2937;
    }

    #body {
        height: 1fr;
        width: 1fr;
        margin-top: 1;
    }

    #left {
        width: 40;
        height: 1fr;
        background: #101010;
        border: round #101010;
        padding: 1 1;
    }

    #center {
        width: 1fr;
        height: 1fr;
        background: #121212;
        border: round #121212;
        padding: 1 1;
        margin: 0 2;
    }

    #cards-scroll {
        height: 1fr;
        margin-top: 1;
    }

    #right {
        width: 37;
        height: 1fr;
        background: #101010;
        border: round #101010;
        padding: 1 1;
    }

    .section-title {
        color: #22C55E;
        text-style: bold;
        margin-bottom: 1;
    }

    #sprints-list {
        height: 1fr;
    }

    .separator {
        color: #252525;
    }

    .left-kpi {
        color: #A3A3A3;
    }

    .sprint-row {
        height: 3;
        width: 1fr;
        padding: 0 1;
        background: transparent;
        align: left middle;
    }

    .sprint-row > .label {
        width: 1fr;
        color: #9CA3AF;
    }

    .sprint-row > .count {
        width: auto;
        content-align: right middle;
        margin-left: 1;
    }

    .sprint-row.-active > .label {
        color: #E5E7EB;
        text-style: bold;
    }

    .sprint-row .done-count {
        color: #22C55E;
        text-style: bold;
    }

    .sprint-retro-star {
        width: auto;
        color: #f59e0b;
        margin-left: 1;
    }

    .sprint-card {
        width: 1fr;
        height: 3;
        background: #111827;
        margin-bottom: 1;
        padding: 0 0;
    }

    .sprint-card.-active {
        height: auto;
        background: #172033;
        border-left: thick #22C55E;
    }

    .sprint-card.-hover {
        background: #1f2937;
    }

    .sprint-action-btn {
        height: 3;
        width: 1fr;
        padding: 1 3;
        color: #4B5563;
    }

    .sprint-action-btn:hover {
        color: #CBD5E1;
        background: #172033;
    }

    #cards-title {
        color: #E5E7EB;
        text-style: bold;
    }

    #cards-subtitle {
        color: #A3A3A3;
        margin-bottom: 1;
    }

    #cards-list {
        layout: vertical;
        width: 1fr;
        height: auto;
    }

    #center.-history {
        margin: 0 0;
    }

    .panel-hidden {
        display: none;
    }

    .history-log-header {
        layout: vertical;
        height: auto;
        width: 1fr;
        background: #0F172A;
        border: round #0F172A;
        padding: 0 1;
        margin-bottom: 1;
    }

    .history-log-head {
        color: #E5E5E5;
        text-style: bold;
    }

    .history-log-sub {
        color: #9CA3AF;
    }

    .history-log-row {
        layout: vertical;
        height: auto;
        background: #171717;
        border: round #171717;
        padding: 0 1;
        margin-bottom: 1;
    }

    .history-log-row.-active {
        background: #172033;
        border: round #172033;
    }

    .history-log-row.-hover {
        background: #1F2937;
        border: round #1F2937;
    }

    .history-log-task {
        color: #E5E5E5;
        text-style: bold;
    }

    .history-log-workflow {
        color: #818CF8;
    }

    .history-log-branch {
        color: #22C55E;
    }

    .history-log-stats {
        color: #A3A3A3;
    }

    .history-log-meta {
        color: #6B7280;
    }

    .cards-row {
        width: 1fr;
        height: 11;
    }

    .card-gap {
        width: 2;
    }

    .row-gap {
        width: 1fr;
        height: 1;
    }

    .story-card {
        width: 1fr;
        background: #171717;
        height: 11;
        padding: 1 2;
    }

    .story-card.-active {
        background: #1A2536;
    }

    .story-card.-hover {
        background: #1f2937;
    }

    .story-card.-empty {
        background: #121212;
        padding: 1 2;
    }

    .story-card .story-badge {
        color: #64748B;
        text-style: bold;
        height: 1;
    }

    .story-card .title {
        color: #E5E7EB;
        text-style: bold;
        height: 1;
        margin-top: 1;
    }

    .story-card .status-ready-for-dev {
        color: #22C55E;
        text-style: bold;
        height: 2;
        content-align: left middle;
    }

    .story-card .status-backlog {
        color: #F59E0B;
        text-style: bold;
        height: 2;
        content-align: left middle;
    }

    .story-card .status-done {
        color: #22C55E;
        text-style: bold;
        height: 2;
        content-align: left middle;
    }

    .story-card .status-in-progress {
        color: #8BE9FD;
        text-style: bold;
        height: 2;
        content-align: left middle;
    }

    .story-card .status-review {
        color: #C084FC;
        text-style: bold;
        height: 2;
        content-align: left middle;
    }

    .story-card .status-blocked {
        color: #ff5555;
        text-style: bold;
        height: 2;
        content-align: left middle;
    }

    .story-card .status-unknown {
        color: #6272a4;
    }

    .story-card .meta {
        color: #9CA3AF;
    }

    .story-card .slug {
        color: #374151;
        text-style: italic;
        width: 1fr;
        content-align: center top;
        margin-top: 1;
    }

    .story-card .card-bottom {
        height: 1;
        width: 1fr;
        dock: bottom;
        align: right middle;
    }

    .story-card .spacer {
        height: 1fr;
    }

    .story-card .cost {
        color: #9CA3AF;
        content-align: left middle;
        width: 1fr;
        height: 1;
    }

    #detail-title {
        color: #F59E0B;
        text-style: bold;
    }

    #sidebar-status-row {
        height: 3;
        background: #0F172A;
        border: round #0F172A;
        padding: 0 1;
        margin-top: 1;
        align: left middle;
        display: none;
    }

    #sidebar-status-row.visible {
        display: block;
    }

    #sidebar-status-row.-kb-focus {
        border: round #22C55E;
    }

    #sidebar-status-val {
        color: #E5E7EB;
        text-style: bold;
        width: 1fr;
        content-align: left middle;
    }

    #detail-body {
        color: #A3A3A3;
        margin-top: 1;
        height: 1fr;
        overflow-y: auto;
    }

    #bottom-nav {
        height: 3;
        margin-top: 1;
        background: #111111;
        border: round #111111;
        padding: 0 1;
        layout: horizontal;
    }

    #bottom-nav-text {
        width: 1fr;
        content-align: left middle;
    }

    #bottom-nav-search {
        width: auto;
        content-align: right middle;
        color: #E5E7EB;
    }

    Footer {
        display: none;
    }

    #phase-banner {
        height: 3;
        background: #111111;
        padding: 0 1;
    }

    #phase-banner-filler {
        width: auto;
        color: #111111;
        margin-right: 2;
        content-align: left middle;
    }

    #phase-banner-text {
        width: 1fr;
        color: #9CA3AF;
        content-align: center middle;
    }

    #retro-row {
        width: 1fr;
        height: 3;
        align: right middle;
        margin-top: 1;
        display: none;
    }

    #retro-btn {
        width: auto;
        height: 3;
        background: #78350f;
        color: #fde68a;
        text-style: bold;
        padding: 0 3;
        content-align: center middle;
    }

    #retro-btn:hover {
        background: #92400e;
        color: #fef3c7;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("up", "nav_up", "Up", show=False),
        Binding("down", "nav_down", "Down", show=False),
        Binding("left", "nav_left", "Left", show=False),
        Binding("right", "nav_right", "Right", show=False),
        Binding("w", "workflows", "Workflows"),
        Binding("enter", "actions", "Actions"),
        Binding("space", "preview", "Preview"),
        Binding("f", "filter", "Filter"),
        Binding("slash", "search", "Search"),
        Binding("1", "tab_sprint", show=False),
        Binding("2", "tab_agents", show=False),
        Binding("3", "tab_workflows", show=False),
        Binding("4", "tab_history", show=False),
        Binding("s", "sprint_plan", "Sprint Plan"),
        Binding("m", "model", "Model"),
        Binding("a", "agents", "Agents"),
        Binding("h", "history", "History"),
        Binding("d", "dev_session", "Dev Session"),
        Binding("c", "cli", "CLI"),
        Binding("shift+h", "bmad_help", "BMad Help"),
        Binding("question_mark", "help", "Help", show=False),
    ]

    selected_model: reactive[Model] = reactive(Model.SONNET)
    HOVER_CLEAR_DELAY_S: ClassVar[float] = 0.16
    _TAB_IDS: ClassVar[list[str]] = ["tab-sprint", "tab-agents", "tab-history"]

    def __init__(self, project_root: Path) -> None:
        super().__init__()
        self._project_root = project_root
        self._state: ProjectState = load_state(project_root)
        self._tui_config: TuiConfig = load_config(project_root)
        self._status_filter: str | None = None
        self._filter_index: int = 0

        self._epics = self._sorted_epics()
        self._selected_epic_index = self._default_epic_index()
        self._selected_story_id: str | None = None
        self._hovered_story_id: str | None = None
        self._hovered_epic_id: str | None = None
        self._hovered_tab: Static | None = None
        self._card_widgets: dict[str, Container] = {}
        self._sprint_widgets: dict[str, Container] = {}
        self._hover_clear_timer = None
        self._focus_zone: str = "cards"   # "cards" | "sprints" | "header"
        self._header_tab_index: int = 0
        self._active_tab: str = "sprint"
        self._last_agent_idx: int = 0
        self._history_entries: list[HistoryEntry] = []
        self._history_selected_idx: int = 0

    def compose(self) -> ComposeResult:
        branch = _current_git_branch(self._project_root)
        with Container(id="root"):
            with Horizontal(id="header"):
                with Vertical(id="header-left"):
                    yield Static(f"~ {self._project_root.name} board", id="header-title")
                    yield Static(f"⎇  {branch}", id="header-branch")
                with Horizontal(id="header-tabs-area"):
                    yield Static("", classes="header-fill")
                    with Horizontal(id="header-tabs"):
                        yield Static("Sprint", classes="tab-chip -active", id="tab-sprint")
                        yield Static("Agents", classes="tab-chip", id="tab-agents")
                        yield Static("History", classes="tab-chip", id="tab-history")

                    yield Static("", classes="header-fill")

            with Horizontal(id="phase-banner"):
                yield Static(f"~ {self._project_root.name} board", id="phase-banner-filler")
                yield Static("", id="phase-banner-text")

            with Horizontal(id="body"):
                with Container(id="left"):
                    yield Static("> sprints (click / enter)", classes="section-title")
                    yield Static("------------------------------", classes="separator")
                    yield Static("stories: backlog 0 | ready 0", classes="left-kpi", id="left-kpi-1")
                    yield Static("review 0 | done 0", classes="left-kpi", id="left-kpi-2")
                    yield Container(id="sprints-list")

                with Container(id="center"):
                    yield Static("> sprint task cards", id="cards-title")
                    yield Static("", id="cards-subtitle")
                    with VerticalScroll(id="cards-scroll"):
                        yield Container(id="cards-list")
                    with Horizontal(id="retro-row"):
                        yield Static("★  Run retrospective", id="retro-btn")

                with Container(id="right"):
                    yield Static("> selected_task", id="detail-title")
                    yield Horizontal(
                        Static("", id="sidebar-status-val"),
                        id="sidebar-status-row",
                    )
                    yield Static("", id="detail-body")

            with Container(id="bottom-nav"):
                yield Static(
                    "[green]q[/] [white]quit[/]   "
                    "[green]r[/] [white]refresh[/]   "
                    "[green]w[/] [white]workflows[/]   "
                    "[green]⏎[/] [white]actions[/]   "
                    "[green]space[/] [white]preview[/]   "
                    "[green]f[/] [white]filter[/]   "
                    "[green]s[/] [white]sprint plan[/]   "
                    "[green]m[/] [white]model[/]   "
                    "[green]a[/] [white]agents[/]   "
                    "[green]h[/] [white]history[/]   "
                    "[green]d[/] [white]dev session[/]   "
                    "[green]c[/] [white]cli[/]",
                    id="bottom-nav-text",
                )
                yield Static("[green]/[/] [white]search[/]", id="bottom-nav-search")

            yield Footer()

    def on_mount(self) -> None:
        purge_legacy_entries(self._project_root)
        purge_trivial_entries(self._project_root)
        self._restore_last_focus()
        self._render_home()
        self._update_phase_banner()
        self._update_retro_btn()
        if self._selected_story_id:
            _focus_id = self._selected_story_id
            def _scroll_to_last_focused() -> None:
                card = self._card_widgets.get(_focus_id)
                if card is not None:
                    card.scroll_visible(top=False)
            self.call_after_refresh(_scroll_to_last_focused)
        if not self._tui_config.cli_tool:
            self.call_after_refresh(self._prompt_cli_first_time)

    def _prompt_cli_first_time(self) -> None:
        """Show CLI picker on first launch (cli_tool not yet set)."""
        installed = available_clis()
        if len(installed) == 1:
            # Only one CLI installed — set it silently without bothering the user.
            self._tui_config.cli_tool = installed[0]
            save_config(self._project_root, self._tui_config)
            return
        self._open_cli_picker()

    # --- Data helpers ---

    def _sorted_epics(self) -> list:
        return sorted(
            self._state.epics,
            key=lambda e: int(e.id) if str(e.id).isdigit() else 999,
        )

    def _restore_last_focus(self) -> None:
        """Set _selected_epic_index and _selected_story_id to the last worked sprint/task.

        Scans history in reverse (most recent first) for the last entry that has
        a non-empty story_id that still exists in the current project state.
        Falls back silently to the default selection if no such entry exists.
        """
        if not self._epics:
            return
        story_ids = {s.id for s in self._state.stories}
        for entry in reversed(load_history(self._project_root)):
            if not entry.story_id or entry.story_id not in story_ids:
                continue
            # Find the matching epic index
            for i, epic in enumerate(self._epics):
                if str(epic.id) == str(entry.epic_id):
                    self._selected_epic_index = i
                    break
            self._selected_story_id = entry.story_id
            return

    @staticmethod
    def _default_story_id_for_sprint(stories: "list[Story]") -> "str | None":
        """Return the ID to focus when switching to a sprint.

        Prefers the first non-done story so that completed work is skipped.
        Falls back to the first story if every story is done.
        """
        if not stories:
            return None
        pending = [s for s in stories if s.yaml_status != "done"]
        return (pending[0] if pending else stories[0]).id

    def _default_epic_index(self) -> int:
        if not self._epics:
            return 0
        for i, epic in enumerate(self._epics):
            if epic.status == "in-progress":
                return i
        for i, epic in enumerate(self._epics):
            if epic.status == "backlog":
                return i
        return 0

    def _stories_for_epic(self, epic_id: str) -> list[Story]:
        epic_key = str(epic_id)
        stories = [s for s in self._state.stories if str(s.epic_id) == epic_key]
        stories.sort(key=_story_sort_key)
        if self._status_filter:
            stories = [s for s in stories if s.yaml_status == self._status_filter]
        return stories

    def _status_counts(self, epic_id: str) -> tuple[int, int, int, int, int]:
        epic_key = str(epic_id)
        stories = [s for s in self._state.stories if str(s.epic_id) == epic_key]
        done = sum(1 for s in stories if s.yaml_status == "done")
        ready = sum(1 for s in stories if s.yaml_status == "ready-for-dev")
        backlog = sum(1 for s in stories if s.yaml_status == "backlog")
        in_progress = sum(1 for s in stories if s.yaml_status == "in-progress")
        review = sum(1 for s in stories if s.yaml_status == "review")
        return backlog, ready, in_progress, review, done

    _BAR_WIDTH: int = 8  # width of progress bar in `_epic_header_cells`

    def _epic_header_cells(self, epic: Epic) -> tuple[str, str, str, str]:
        """Return (id_cell, stat_cell, bar_cell, act_cell) Rich-markup strings for an epic header row.

        Column layout:
          id_cell  → ID column      : ▌ accent + bold epic ID
          stat_cell → Status column : symbol + status label in epic colour
          bar_cell → Title column   : "Epic N" label
          act_cell → Action column  : progress bar + done/total count
        """
        col = epic.rich_style
        status_map: dict[str, tuple[str, str]] = {
            "in-progress": ("◆", "In Progress"),
            "done":        ("✓", "Done"),
            "backlog":     ("·", "Backlog"),
            "blocked":     ("⊘", "Blocked"),
            "review":      ("◈", "Review"),
        }
        sym, lbl = status_map.get(epic.status, ("·", epic.status.replace("-", " ").title()))

        stories = self._stories_for_epic(epic.id)
        total = len(stories)
        done = sum(1 for s in stories if s.yaml_status == "done")
        filled = round(done / total * self._BAR_WIDTH) if total > 0 else 0
        bar = "█" * filled + "░" * (self._BAR_WIDTH - filled)

        id_cell   = f"[bold {col}]▌ E{epic.id}[/bold {col}]"
        stat_cell = f"[{col} bold]{sym} {lbl}[/{col} bold]"
        bar_cell  = f"[bold {col}]Epic {epic.id}[/bold {col}]"
        act_cell  = f"[dim {col}]{bar}  {done}/{total}[/dim {col}]"
        return id_cell, stat_cell, bar_cell, act_cell

    def _card_status_class(self, story: Story) -> str:
        status = story.yaml_status
        if status == "needs-story":
            status = "backlog"
        elif status not in {"ready-for-dev", "backlog", "done", "in-progress", "review", "blocked"}:
            status = "unknown"
        return f"status-{status}"

    def _story_cost_line(self, story: Story) -> str:
        # Cost data isn't wired yet; hide until real values are available.
        return ""

    # --- Rendering ---

    def _render_home(self) -> None:
        self._active_tab = "sprint"
        self._apply_tab_classes()
        self._set_history_layout(False)
        self._render_left_kpis()
        self._render_center_title()
        self._render_sprints()
        self._render_cards()
        self._render_detail()
        self._update_phase_banner()
        self._update_retro_btn()

    def _apply_tab_classes(self) -> None:
        tab_map = {
            "sprint": "tab-sprint",
            "agents": "tab-agents",
            "history": "tab-history",
        }
        active_id = tab_map.get(self._active_tab, "tab-sprint")
        for tab_id in self._TAB_IDS:
            tab = self.query_one(f"#{tab_id}", Static)
            tab.remove_class("-hover")
            if tab_id == active_id:
                tab.add_class("-active")
            else:
                tab.remove_class("-active")
        self._hovered_tab = None

    def _set_history_layout(self, active: bool) -> None:
        left = self.query_one("#left", Container)
        right = self.query_one("#right", Container)
        center = self.query_one("#center", Container)
        phase = self.query_one("#phase-banner", Horizontal)

        if active:
            left.add_class("panel-hidden")
            right.add_class("panel-hidden")
            center.add_class("-history")
            phase.add_class("panel-hidden")
            self._focus_zone = "cards"
        else:
            left.remove_class("panel-hidden")
            right.remove_class("panel-hidden")
            center.remove_class("-history")
            phase.remove_class("panel-hidden")

    def _render_history_home(self) -> None:
        self._active_tab = "history"
        self._apply_tab_classes()
        self._set_history_layout(True)
        title = self.query_one("#cards-title", Static)
        subtitle = self.query_one("#cards-subtitle", Static)
        cards_list = self.query_one("#cards-list", Container)
        detail = self.query_one("#detail-body", Static)
        status_row = self.query_one("#sidebar-status-row")

        title.update("> history log (all entries)")
        subtitle.update("")
        status_row.remove_class("visible")
        detail.update("")
        cards_list.remove_children()

        entries = list(reversed(load_history(self._project_root)))
        self._history_entries = entries
        self._history_selected_idx = min(self._history_selected_idx, max(0, len(entries) - 1))

        cards_list.mount(
            Container(
                Static("task | branch worked | stats", classes="history-log-head"),
                Static("Click to select  ·  double-click or Enter to open  ·  hover to highlight.", classes="history-log-sub"),
                classes="history-log-header",
            )
        )
        if not entries:
            cards_list.mount(Static("No history yet.", classes="history-log-sub"))
            return
        for i, e in enumerate(entries):
            cards_list.mount(_DashboardHistoryRow(e, i, active=(i == self._history_selected_idx)))

    def _set_history_active(self, idx: int) -> None:
        rows = list(self.query(_DashboardHistoryRow))
        if not rows:
            self._history_selected_idx = 0
            return
        idx = max(0, min(len(rows) - 1, idx))
        for i, row in enumerate(rows):
            row.set_class(i == idx, "-active")
        self._history_selected_idx = idx
        rows[idx].scroll_visible()

    def _render_left_kpis(self) -> None:
        if not self._epics:
            self.query_one("#left-kpi-1", Static).update("stories: backlog 0 | ready 0")
            self.query_one("#left-kpi-2", Static).update("review 0 | done 0")
            return
        epic_id = self._epics[self._selected_epic_index].id
        backlog, ready, _in_progress, review, done = self._status_counts(epic_id)
        self.query_one("#left-kpi-1", Static).update(f"stories: backlog {backlog} | ready {ready}")
        self.query_one("#left-kpi-2", Static).update(f"review {review} | done {done}")

    def _render_center_title(self) -> None:
        title = self.query_one("#cards-title", Static)
        subtitle = self.query_one("#cards-subtitle", Static)
        if not self._epics:
            title.update("> sprint task cards")
            subtitle.update("no sprint selected")
            return
        epic = self._epics[self._selected_epic_index]
        if epic.title:
            title.update(epic.title)
        else:
            title.update(f"> sprint_{epic.id} task cards")
        subtitle.update("")

    def _render_sprints(self) -> None:
        container = self.query_one("#sprints-list", Container)
        container.remove_children()
        self._sprint_widgets = {}

        for i, epic in enumerate(self._epics):
            stories = [s for s in self._state.stories if str(s.epic_id) == str(epic.id)]
            done = sum(1 for s in stories if s.yaml_status == "done")
            total = len(stories)
            active = i == self._selected_epic_index

            # Retro condition: all stories done, sprint not closed, retro not done
            needs_retro = (
                bool(stories)
                and done == total
                and epic.status != "done"
                and epic.retrospective_status not in ("done",)
            )

            status_short = epic.status.replace("-", " ")
            label = Static(f"epic-{epic.id}  {status_short}", classes="label", markup=False)
            count = Static(f"{done}/{total}", classes="count done-count" if total > 0 and done == total else "count label", markup=False)
            row_children: list = [label, count]
            if needs_retro:
                row_children.append(Static("★", classes="sprint-retro-star"))
            row = Horizontal(*row_children, classes="sprint-row -active" if active else "sprint-row")
            setattr(row, "_epic_id", epic.id)

            if active:
                # Show sprint planning only when the sprint hasn't started yet
                # Show correct course only when sprint is actively in-progress or blocked
                sprint_actions: list[tuple[str, str]] = []
                if epic.status in ("backlog", ""):
                    sprint_actions.append(("sprint-planning", "▶ sprint planning"))
                if epic.status in ("in-progress", "blocked"):
                    sprint_actions.append(("correct-course", "⟳ correct course"))

                if sprint_actions:
                    children: list = [row]
                    for wf_key, wf_label in sprint_actions:
                        btn = Static(wf_label, classes="sprint-action-btn")
                        setattr(btn, "_sprint_workflow_key", wf_key)
                        children.append(btn)
                    card = Container(*children, classes="sprint-card -active")
                else:
                    card = Container(row, classes="sprint-card -active")
            else:
                card = Container(row, classes="sprint-card")

            setattr(card, "_epic_id", epic.id)
            self._sprint_widgets[epic.id] = card
            container.mount(card)

        self._update_retro_btn()

    def _update_sprint_selection(self, old_index: int | None, new_index: int) -> None:
        """Update sprint active state in-place without a full re-render of the list."""
        if old_index is not None and 0 <= old_index < len(self._epics):
            old_epic = self._epics[old_index]
            old_card = self._sprint_widgets.get(old_epic.id)
            if old_card is not None:
                old_card.remove_class("-active")
                for row in old_card.query(".sprint-row"):
                    row.remove_class("-active")
                for btn in old_card.query(".sprint-action-btn"):
                    btn.remove()

        if 0 <= new_index < len(self._epics):
            new_epic = self._epics[new_index]
            new_card = self._sprint_widgets.get(new_epic.id)
            if new_card is not None:
                new_card.add_class("-active")
                for row in new_card.query(".sprint-row"):
                    row.add_class("-active")
                sprint_actions: list[tuple[str, str]] = []
                if new_epic.status in ("backlog", ""):
                    sprint_actions.append(("sprint-planning", "▶ sprint planning"))
                if new_epic.status in ("in-progress", "blocked"):
                    sprint_actions.append(("correct-course", "⟳ correct course"))
                for wf_key, wf_label in sprint_actions:
                    btn = Static(wf_label, classes="sprint-action-btn")
                    setattr(btn, "_sprint_workflow_key", wf_key)
                    new_card.mount(btn)

    def _switch_sprint(self, new_index: int) -> None:
        """Change the selected sprint without re-rendering the sprint list."""
        old_index = self._selected_epic_index
        self._selected_epic_index = new_index
        self._selected_story_id = None
        self._hovered_story_id = None
        self._hovered_epic_id = None
        self._update_sprint_selection(old_index, new_index)
        self._render_left_kpis()
        self._render_center_title()
        self._render_cards()
        self._render_detail()
        self._update_phase_banner()
        self._update_retro_btn()

    def _render_cards(self) -> None:
        cards_list = self.query_one("#cards-list", Container)
        self._card_widgets = {}

        with self.app.batch_update():
            cards_list.remove_children()

            if not self._epics:
                cards_list.mount(Static("No sprint data."))
                self._selected_story_id = None
                return

            epic = self._epics[self._selected_epic_index]
            stories = self._stories_for_epic(epic.id)
            if stories and (self._selected_story_id not in {s.id for s in stories}):
                self._selected_story_id = self._default_story_id_for_sprint(stories)

            cards: list[Container] = []
            for story in stories:
                badge = story.short_id.replace("-", ".")
                raw_title = story.doc_title
                # Strip common "Story X.X: " / "Story X.X - " prefixes from doc title
                clean_title = re.sub(r"^Story\s+[\d.]+\s*[:\-–]\s*", "", raw_title, flags=re.IGNORECASE).strip() or raw_title
                status = story.yaml_status
                cost = self._story_cost_line(story)
                active = story.id == self._effective_story_id()

                card_classes = "story-card -active" if active else "story-card"
                children = [
                    Static(f"[{badge}]", classes="story-badge"),
                    Static(clean_title[:48], classes="title"),
                    Static(story.id, classes="slug"),
                    Horizontal(
                        Static(cost, classes="cost"),
                        _CardStatusBlock(status),
                        classes="card-bottom",
                    ),
                ]
                children.append(Static(cost, classes="cost"))
                card = Container(*children, classes=card_classes)
                setattr(card, "_story_id", story.id)
                self._card_widgets[story.id] = card
                cards.append(card)

            # keep 4-column rhythm with placeholders
            while len(cards) % 4 != 0 and len(cards) > 0:
                cards.append(Container(classes="story-card -empty"))
                stories.append(Story(id="_", yaml_status="backlog", epic_id=epic.id, file_path=None))

            row_count = len(cards) // 4
            for row_index, i in enumerate(range(0, len(cards), 4)):
                row_cards = cards[i : i + 4]
                row_children = []
                for j, card in enumerate(row_cards):
                    row_children.append(card)
                    if j < len(row_cards) - 1:
                        row_children.append(Container(classes="card-gap"))
                row = Horizontal(*row_children, classes="cards-row")
                cards_list.mount(row)
                if row_index < row_count - 1:
                    cards_list.mount(Container(classes="row-gap"))

    def _render_detail(self) -> None:
        detail = self.query_one("#detail-body", Static)
        status_row = self.query_one("#sidebar-status-row")
        status_val = self.query_one("#sidebar-status-val", Static)
        target_story_id = self._effective_story_id()
        story = None
        for s in self._state.stories:
            if s.id == target_story_id:
                story = s
                break

        if story is None:
            detail.update("Select a task card.")
            status_row.remove_class("visible")
            return

        # Update sidebar status chip
        status_row.add_class("visible")
        status_val.update(f"{story.effective_status.emoji} {story.yaml_status}   ▼")

        status_color = {
            "ready-for-dev": "#22C55E",
            "done": "#22C55E",
            "backlog": "#F59E0B",
            "in-progress": "#8BE9FD",
            "review": "#C084FC",
        }.get(story.yaml_status, "#A3A3A3")

        workflow_key = story.primary_workflow
        if workflow_key:
            next_action = f"/bmad-bmm-{workflow_key}  story_key={story.short_id}-..."
        else:
            next_action = "none"

        done_count = 0
        if self._epics:
            epic = self._epics[self._selected_epic_index]
            done_count = sum(
                1 for s in self._state.stories
                if str(s.epic_id) == str(epic.id) and s.yaml_status == "done"
            )
        done_label = "none" if done_count == 0 else str(done_count)

        lines = [
            f"[#E5E5E5]id: {story.id}[/]",
            f"next action: {next_action}",
            "[#252525]------------------------------[/]",
            "",
            "[bold #E5E5E5]> task_description[/]",
            story.title,
            "",
            f"current sprint done cards: {done_label}",
        ]

        # Show open subtasks whenever the story file has any (partial or not yet started)
        if story.file_path:
            open_tasks, tasks_done = _parse_open_subtasks(story.file_path)
            total_tasks = tasks_done + len(open_tasks)
            if open_tasks:
                pct = f"{tasks_done}/{total_tasks} done" if total_tasks > 0 else ""
                lines += [
                    "",
                    "[#252525]------------------------------[/]",
                    f"[bold #E5E5E5]> open subtasks[/] [#64748B]({pct})[/]",
                    "",
                ]
                for t in open_tasks:
                    label = t if len(t) <= 32 else t[:30] + "…"
                    lines.append(f"[#F59E0B]○[/] [#CBD5E1]{label}[/]")

        detail.update("\n".join(lines))

    # --- Interaction ---

    def _effective_story_id(self) -> str | None:
        return self._hovered_story_id or self._selected_story_id

    def _set_card_active(self, story_id: str | None, active: bool) -> None:
        if not story_id:
            return
        card = self._card_widgets.get(story_id)
        if not card:
            return
        if active:
            card.add_class("-active")
        else:
            card.remove_class("-active")

    def _set_card_hover(self, story_id: str | None) -> None:
        prev = self._hovered_story_id
        if prev == story_id:
            return
        if prev and prev in self._card_widgets:
            self._card_widgets[prev].remove_class("-hover")
        self._hovered_story_id = story_id
        if story_id and story_id in self._card_widgets:
            self._card_widgets[story_id].add_class("-hover")

    def _set_sprint_hover(self, epic_id: str | None) -> None:
        prev = self._hovered_epic_id
        if prev == epic_id:
            return
        if prev and prev in self._sprint_widgets:
            self._sprint_widgets[prev].remove_class("-hover")
        self._hovered_epic_id = epic_id
        if epic_id and epic_id in self._sprint_widgets:
            self._sprint_widgets[epic_id].add_class("-hover")

    def _set_tab_hover(self, tab: Static | None) -> None:
        prev = self._hovered_tab
        if prev is tab:
            return
        if prev is not None:
            prev.remove_class("-hover")
        self._hovered_tab = tab
        if tab is not None and "-active" not in tab.classes:
            tab.add_class("-hover")

    def _set_hover_story(self, story_id: str | None) -> None:
        self._set_card_hover(story_id)
        self._render_detail()

    def _set_selected_story(self, story_id: str | None) -> None:
        previous = self._selected_story_id
        self._selected_story_id = story_id
        # clear hover on the newly selected card
        if story_id and story_id in self._card_widgets:
            self._card_widgets[story_id].remove_class("-hover")
        self._hovered_story_id = None
        if previous != story_id:
            self._set_card_active(previous, False)
            self._set_card_active(story_id, True)
            self._render_detail()
        if story_id:
            card = self._card_widgets.get(story_id)
            if card is not None:
                card.scroll_visible(top=False)

    def _current_sprint_stories(self) -> list[Story]:
        if not self._epics:
            return []
        epic = self._epics[self._selected_epic_index]
        return self._stories_for_epic(epic.id)

    def _move_card_selection(self, delta: int) -> None:
        stories = self._current_sprint_stories()
        if not stories:
            return
        ids = [s.id for s in stories]
        current_id = self._selected_story_id if self._selected_story_id in ids else ids[0]
        idx = ids.index(current_id)
        next_idx = max(0, min(len(ids) - 1, idx + delta))
        if next_idx != idx:
            self._cancel_hover_clear_timer()
            self._set_selected_story(ids[next_idx])

    def _cancel_hover_clear_timer(self) -> None:
        if self._hover_clear_timer is not None:
            try:
                self._hover_clear_timer.stop()
            except Exception:
                pass
            self._hover_clear_timer = None

    def _schedule_hover_clear(self) -> None:
        if (self._hovered_story_id is None and self._hovered_epic_id is None and self._hovered_tab is None) or self._hover_clear_timer is not None:
            return
        self._hover_clear_timer = self.set_timer(self.HOVER_CLEAR_DELAY_S, self._clear_hover_after_delay)

    def _clear_hover_after_delay(self) -> None:
        self._hover_clear_timer = None
        self._set_card_hover(None)
        self._set_sprint_hover(None)
        self._set_tab_hover(None)
        self._render_detail()

    def _widget_meta(self, node, key: str) -> str | None:
        current = node
        while current is not None:
            value = getattr(current, key, None)
            if value:
                return str(value)
            current = getattr(current, "parent", None)
        return None

    def on_click(self, event) -> None:  # type: ignore[override]
        node = event.widget

        # Retrospective floating button
        if getattr(node, "id", "") == "retro-btn":
            self._run_sprint_workflow("retrospective")
            return

        # Sprint-level action buttons in the left panel
        sprint_wf = self._widget_meta(node, "_sprint_workflow_key")
        if sprint_wf is not None:
            self._run_sprint_workflow(sprint_wf)
            return

        node_id = getattr(node, "id", "")

        if node_id == "tab-workflows":
            self.action_workflows()
            return
        if node_id == "tab-agents":
            self.action_agents()
            return
        if node_id == "tab-sprint":
            self.action_tab_sprint()
            return
        if node_id == "tab-history":
            self.action_history()
            return

        if self._active_tab == "history":
            return

        epic_id = self._widget_meta(node, "_epic_id")
        if epic_id is not None:
            self._cancel_hover_clear_timer()
            for i, epic in enumerate(self._epics):
                if epic.id == epic_id:
                    self._focus_zone = "sprints"
                    self._switch_sprint(i)
                    return

        story_id = self._widget_meta(node, "_story_id")
        if story_id is not None:
            self._cancel_hover_clear_timer()
            self._focus_zone = "cards"
            story = next((s for s in self._state.stories if s.id == story_id), None)
            if story_id == self._selected_story_id:
                # Second left-click on already-selected card → open modal
                if story is not None:
                    self.push_screen(
                        StoryActionModal(story, self.selected_model, self._state.sprint_status_path, self._project_root, auto_despawn=self._tui_config.auto_despawn_yolo),
                        self._on_modal_result,
                    )
            else:
                # First click → select the card
                self._hovered_epic_id = None
                self._set_selected_story(story_id)
            return

        node_id = getattr(node, "id", "") or ""
        parent_id = getattr(getattr(node, "parent", None), "id", "") or ""
        if node_id in ("sidebar-status-row", "sidebar-status-val") or parent_id == "sidebar-status-row":
            self._open_sidebar_status_overlay()

    def on__dashboard_history_row_highlighted(self, event: _DashboardHistoryRow.Highlighted) -> None:
        self._set_history_active(event.index)
        # Return focus to the screen so Dashboard's keyboard bindings (↑↓ Enter) keep working.
        # Clicking a row sets focus to the VerticalScroll container, which would otherwise
        # intercept arrow-key events for scrolling before they reach Dashboard's nav bindings.
        self.set_focus(None)

    def on__dashboard_history_row_selected(self, event: _DashboardHistoryRow.Selected) -> None:
        self._set_history_active(event.index)
        if 0 <= event.index < len(self._history_entries):
            self._run_history_entry(self._history_entries[event.index])

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._active_tab == "history":
            widget = event.widget
            if isinstance(widget, Static) and "tab-chip" in widget.classes:
                self._cancel_hover_clear_timer()
                self._set_tab_hover(widget)
                return
            self._schedule_hover_clear()
            return

        story_id = self._widget_meta(event.widget, "_story_id")
        if story_id is not None:
            self._cancel_hover_clear_timer()
            self._set_hover_story(story_id)
            self._set_sprint_hover(None)
            self._set_tab_hover(None)
            return

        epic_id = self._widget_meta(event.widget, "_epic_id")
        if epic_id is not None:
            self._cancel_hover_clear_timer()
            self._set_sprint_hover(epic_id)
            self._set_card_hover(None)
            self._set_tab_hover(None)
            return

        # Tab chip hover
        widget = event.widget
        if isinstance(widget, Static) and "tab-chip" in widget.classes:
            self._cancel_hover_clear_timer()
            self._set_tab_hover(widget)
            self._set_card_hover(None)
            self._set_sprint_hover(None)
            return

        self._schedule_hover_clear()

    def action_refresh(self) -> None:
        self._cancel_hover_clear_timer()
        self._state = load_state(self._project_root)
        self._epics = self._sorted_epics()
        self._selected_epic_index = min(self._selected_epic_index, max(0, len(self._epics) - 1))
        self._selected_story_id = None
        self._hovered_story_id = None
        self._hovered_epic_id = None
        self._hovered_tab = None
        if self._active_tab == "history":
            self._render_history_home()
        else:
            self._render_home()
        self.notify("Refreshed", timeout=1.5)

    def on_story_action_modal_status_changed(self, event: StoryActionModal.StatusChanged) -> None:
        """Live-update the card and sidebar when status is changed from the action modal."""
        self._apply_status_update(event.story_id, event.status)

    def _on_modal_result(self, result: tuple | None) -> None:
        if result is None:
            return
        key, model, *rest = result
        session_id = rest[0] if rest else ""
        # auto_despawn is the 4th element (index 1 in rest), default to current config
        auto_despawn: bool = bool(rest[1]) if len(rest) > 1 else self._tui_config.auto_despawn_yolo
        self.selected_model = model

        story = next((s for s in self._state.stories if s.id == self._selected_story_id), None)
        wf = WORKFLOWS.get(key)
        if wf is None or story is None:
            self.notify(f"Unknown workflow: {key}", timeout=2.0)
            return

        missing = check_prerequisites()
        if missing:
            self.notify(f"Missing: {', '.join(missing)} — install then retry", timeout=4.0)
            return

        # Persist model choice and auto_despawn setting
        self._tui_config.set_model_for(key, model.value)
        self._tui_config.auto_despawn_yolo = auto_despawn
        save_config(self._project_root, self._tui_config)

        state = self._state

        # Capture focus anchors before suspending so we can restore them after the run
        saved_epic_id = story.epic_id
        saved_story_id = story.id

        with self.app.suspend():
            entry = run_workflow(workflow_key=key, state=state, model=model, story=story, session_id=session_id, auto_despawn=auto_despawn, cli_tool=self._tui_config.cli_tool)

        def _on_done() -> None:
            # Reload state after agent finishes
            self._state = load_state(self._project_root)
            self._epics = self._sorted_epics()

            # Restore sprint selection by epic ID (not by index, which can shift after reload)
            epic_ids = [str(e.id) for e in self._epics]
            if str(saved_epic_id) in epic_ids:
                self._selected_epic_index = epic_ids.index(str(saved_epic_id))
            else:
                self._selected_epic_index = min(self._selected_epic_index, max(0, len(self._epics) - 1))

            # Preserve story selection so _render_cards applies the -active class correctly
            self._selected_story_id = saved_story_id

            self._render_home()

            # Scroll the focused card into view once the DOM has settled
            def _restore_card_focus() -> None:
                card = self._card_widgets.get(saved_story_id)
                if card is not None:
                    card.scroll_visible(top=False)

            self.call_after_refresh(_restore_card_focus)
            self.notify(f"✓ {wf.label} complete — state reloaded", timeout=3.0)

        self._save_run_entry(entry, _on_done)

    def _open_sidebar_status_overlay(self) -> None:
        story_id = self._effective_story_id()
        if not story_id:
            return
        story = next((s for s in self._state.stories if s.id == story_id), None)
        if story is None:
            return
        row = self.query_one("#sidebar-status-row")
        r = row.region
        self.push_screen(
            StatusDropdownOverlay(story.effective_status, anchor=(r.x, r.y, r.width, r.height)),
            lambda result: self._on_sidebar_status_chosen(result, story_id),
        )

    def _apply_status_update(self, story_id: str, status: StoryStatus) -> None:
        """Surgically update status in-memory and refresh only the affected widgets."""
        # 1. Mutate the in-memory story so counts stay accurate without a reload
        story = next((s for s in self._state.stories if s.id == story_id), None)
        if story is None:
            return
        story.yaml_status = status.value

        # 2. Update the story card's _CardStatusBlock
        card = self._card_widgets.get(story_id)
        if card is not None:
            for child in card.query(_CardStatusBlock):
                child._update_status(status.value)
                break

        # 3. Update sidebar chip if this story is currently shown
        if self._effective_story_id() == story_id:
            try:
                self.query_one("#sidebar-status-row").add_class("visible")
                self.query_one("#sidebar-status-val", Static).update(
                    f"{status.emoji} {status.value}   ▼"
                )
            except Exception:
                pass

        # 4. Refresh just the KPI counts
        self._render_left_kpis()

    def _on_sidebar_status_chosen(self, status: StoryStatus | None, story_id: str) -> None:
        if status is None:
            return
        story = next((s for s in self._state.stories if s.id == story_id), None)
        try:
            _set_story_status(self._state.sprint_status_path, story_id, status.value, story.file_path if story else None)
        except Exception as exc:
            self.notify(f"Failed to update status: {exc}", severity="error", timeout=3.0)
            return
        self._apply_status_update(story_id, status)
        self.notify(f"✓ {story_id} → {status.value}", timeout=2.0)

    def action_actions(self) -> None:
        if self._active_tab == "history":
            if not self._history_entries:
                self.notify("No history yet.", timeout=1.5)
                return
            self._run_history_entry(self._history_entries[self._history_selected_idx])
            return
        if self._focus_zone == "right":
            self._open_sidebar_status_overlay()
            return
        if self._selected_story_id is None:
            self.notify("Select a story first", timeout=1.5)
            return
        story = next((s for s in self._state.stories if s.id == self._selected_story_id), None)
        if story is not None:
            self.push_screen(StoryActionModal(story, self.selected_model, self._state.sprint_status_path, self._project_root, auto_despawn=self._tui_config.auto_despawn_yolo), self._on_modal_result)

    def action_preview(self) -> None:
        if self._selected_story_id is None:
            self.notify("Select a story first", timeout=1.5)
            return
        story = next((s for s in self._state.stories if s.id == self._selected_story_id), None)
        if story is not None:
            self.push_screen(StoryActionModal(story, self.selected_model, self._state.sprint_status_path, self._project_root, auto_despawn=self._tui_config.auto_despawn_yolo), self._on_modal_result)

    def action_filter(self) -> None:
        all_stories = self._state.stories
        counts = [
            len(all_stories) if status_val is None
            else sum(1 for s in all_stories if s.yaml_status == status_val)
            for status_val, _label, _key in FILTER_LABELS
        ]

        def _on_filter_result(index: int | None) -> None:
            if index is not None:
                self._set_filter(index)

        self.push_screen(FilterPickerModal(self._filter_index, counts), _on_filter_result)

    def action_cli(self) -> None:
        self._open_cli_picker()

    def _open_cli_picker(self) -> None:
        installed = available_clis()
        if not installed:
            self.notify("No supported CLI found (install copilot or claude)", timeout=4.0)
            return
        current = self._tui_config.cli_tool or installed[0]

        def _on_cli_result(choice: str | None) -> None:
            if choice is None:
                return
            self._tui_config.cli_tool = choice
            save_config(self._project_root, self._tui_config)
            self.notify(f"CLI set to: {choice}", timeout=2.0)

        self.push_screen(CliPickerModal(current, installed), _on_cli_result)

    def _save_run_entry(self, entry: "HistoryEntry | None", on_done: "Callable[[], None]") -> None:
        """Persist a history entry, prompting for a name when the session had no story context.

        - entry is None  → trivial/empty session; skip saving, call on_done immediately.
        - entry.task_name set (story run) → save straight away, no prompt.
        - entry.task_name empty + zero code changes → nothing to label or save; call on_done.
        - entry.task_name empty + real changes → show _NameSessionModal; save with the user's
          label if provided, save without one if skipped, then call on_done.
        """
        if entry is None:
            on_done()
            return

        if entry.task_name:
            append_history(self._project_root, entry)
            on_done()
            return

        if has_zero_code_changes(entry):
            on_done()
            return

        def _on_name(name: "str | None") -> None:
            if name:
                entry.task_name = name
            append_history(self._project_root, entry)
            on_done()

        self.push_screen(_NameSessionModal(), _on_name)

    def _run_sprint_workflow(self, workflow_key: str) -> None:
        """Run a sprint-level workflow (no story context) — used by left-panel action buttons."""
        wf = WORKFLOWS.get(workflow_key)
        if wf is None:
            self.notify(f"Workflow '{workflow_key}' not registered", timeout=2.0)
            return
        missing = check_prerequisites()
        if missing:
            self.notify(f"Missing: {', '.join(missing)} — install then retry", timeout=4.0)
            return
        with self.app.suspend():
            entry = run_workflow(workflow_key, self._state, self.selected_model, story=None, cli_tool=self._tui_config.cli_tool)

        def _on_done() -> None:
            self._state = load_state(self._project_root)
            self._epics = self._sorted_epics()
            self._render_home()
            self.notify(f"✓ {wf.label} complete — state reloaded", timeout=3.0)

        self._save_run_entry(entry, _on_done)

    def action_sprint_plan(self) -> None:
        self._run_sprint_workflow("sprint-planning")

    def action_model(self) -> None:
        models = list(Model)
        idx = models.index(self.selected_model)
        self.selected_model = models[(idx + 1) % len(models)]
        self.notify(f"Model: {self.selected_model.label()}", timeout=1.5)

    def action_agents(self) -> None:
        self._last_agent_idx = 0
        self._push_agents_screen()

    def _push_agents_screen(self, initial_idx: int | None = None) -> None:
        self._active_tab = "agents"
        self._apply_tab_classes()
        branch = _current_git_branch(self._project_root)
        idx = initial_idx if initial_idx is not None else self._last_agent_idx
        self.push_screen(AgentPickerScreen(self._project_root, branch, self._state, initial_idx=idx), self._on_agent_modal_result)

    def _on_agent_modal_result(self, result: tuple | None) -> None:
        if result is None:
            return
        if result[0] == "__nav__":
            if result[1] == "history":
                self.action_history()
            else:
                self._render_home()
            return
        agent, wf_key, model = result
        _picker_agents = load_agents(self._project_root)
        self._last_agent_idx = next((i for i, a in enumerate(_picker_agents) if a == agent), 0)
        self._execute_workflow(wf_key, model)

    def _execute_workflow(self, wf_key: str, model: "Model") -> None:
        """Run a workflow by key and model, then reload state."""
        wf = WORKFLOWS.get(wf_key)
        if wf is None:
            self.notify(f"Unknown workflow: {wf_key}", timeout=2.0)
            return

        missing = check_prerequisites()
        if missing:
            self.notify(f"Missing: {', '.join(missing)} — install then retry", timeout=4.0)
            return

        self._tui_config.set_model_for(wf_key, model.value)
        save_config(self._project_root, self._tui_config)

        state = self._state

        with self.app.suspend():
            entry = run_workflow(workflow_key=wf_key, state=state, model=model, story=None, from_menu=True, cli_tool=self._tui_config.cli_tool)

        def _on_done() -> None:
            self._state = load_state(self._project_root)
            self._epics = self._sorted_epics()
            self._render_home()
            self.notify(f"✓ {wf.label} complete — state reloaded", timeout=3.0)

        self._save_run_entry(entry, _on_done)

    def action_history(self) -> None:
        self._render_history_home()

    def _on_history_result(self, entry: "HistoryEntry | None") -> None:
        if entry is None:
            return
        self._run_history_entry(entry)

    def _run_history_entry(self, entry: HistoryEntry) -> None:
        missing = check_prerequisites()
        if missing:
            self.notify(f"Missing: {', '.join(missing)} — install then retry", timeout=4.0)
            return

        wf = WORKFLOWS.get(entry.workflow)
        if wf is None:
            self.notify(f"Unknown workflow: {entry.workflow}", timeout=2.0)
            return

        try:
            model = Model(entry.model)
        except ValueError:
            model = self.selected_model

        story: Story | None = None
        if entry.story_id:
            story = next((s for s in self._state.stories if s.id == entry.story_id), None)

        action = "Resuming" if entry.session_id else "Re-running"
        self.notify(f"{action}: {wf.label}", timeout=2.0)

        state = self._state
        with self.app.suspend():
            new_entry = run_workflow(
                workflow_key=entry.workflow,
                state=state,
                model=model,
                story=story,
                epic_id=entry.epic_id or None,
                session_id=entry.session_id,
                task_name=entry.task_name,
                cli_tool=self._tui_config.cli_tool,
            )

        def _on_done() -> None:
            self._state = load_state(self._project_root)
            self._epics = self._sorted_epics()
            if self._active_tab == "history":
                self._render_history_home()
            else:
                self._render_home()
            self.notify(f"✓ {wf.label} complete — state reloaded", timeout=3.0)

        self._save_run_entry(new_entry, _on_done)

    def _on_workflow_modal_result(self, result: tuple | None) -> None:
        if result is None:
            return
        wf_key, model = result
        self._execute_workflow(wf_key, model)

    def action_workflows(self) -> None:
        self.push_screen(WorkflowPickerModal(), self._on_workflow_modal_result)

    def action_nav_left(self) -> None:
        if self._active_tab == "history":
            if self._focus_zone == "header":
                self._move_tab(-1)
            return
        if self._focus_zone == "header":
            self._move_tab(-1)
        elif self._focus_zone == "sprints":
            pass  # no-op at leftmost panel
        elif self._focus_zone == "right":
            self._enter_zone("cards")
        else:  # cards
            stories = self._current_sprint_stories()
            ids = [s.id for s in stories]
            if not ids:
                self._enter_zone("sprints")
                return
            current_id = self._selected_story_id if self._selected_story_id in ids else ids[0]
            idx = ids.index(current_id)
            if idx % 4 == 0:
                self._enter_zone("sprints")
            else:
                self._focus_zone = "cards"
                self._move_card_selection(-1)

    def action_nav_right(self) -> None:
        if self._active_tab == "history":
            if self._focus_zone == "header":
                self._move_tab(1)
            return
        if self._focus_zone == "header":
            self._move_tab(1)
        elif self._focus_zone == "sprints":
            self._enter_zone("cards")
        elif self._focus_zone == "right":
            pass  # already at rightmost
        else:  # cards
            stories = self._current_sprint_stories()
            ids = [s.id for s in stories]
            if not ids:
                return
            current_id = self._selected_story_id if self._selected_story_id in ids else ids[0]
            idx = ids.index(current_id)
            next_idx = min(len(ids) - 1, idx + 1)
            if next_idx == idx:
                # at last card — enter right sidebar zone if a story is selected and visible
                try:
                    row = self.query_one("#sidebar-status-row")
                    if "visible" in row.classes:
                        self._enter_zone("right")
                except Exception:
                    pass
            else:
                self._move_card_selection(1)

    def action_nav_up(self) -> None:
        if self._active_tab == "history":
            if self._focus_zone == "header":
                return
            self._set_history_active(self._history_selected_idx - 1)
            return
        if self._focus_zone == "header":
            pass  # already at top
        elif self._focus_zone == "sprints":
            if self._selected_epic_index > 0:
                self._switch_sprint(self._selected_epic_index - 1)
        else:  # cards
            stories = self._current_sprint_stories()
            ids = [s.id for s in stories]
            if not ids:
                self._enter_zone("header")
                return
            current_id = self._selected_story_id if self._selected_story_id in ids else ids[0]
            idx = ids.index(current_id)
            if idx < 4:
                self._enter_zone("header")
            else:
                self._move_card_selection(-4)

    def action_nav_down(self) -> None:
        if self._active_tab == "history":
            if self._focus_zone == "header":
                self._focus_zone = "cards"
                self._set_history_active(self._history_selected_idx)
                return
            self._set_history_active(self._history_selected_idx + 1)
            return
        if self._focus_zone == "header":
            self._enter_zone("cards")
        elif self._focus_zone == "sprints":
            if self._selected_epic_index < len(self._epics) - 1:
                self._switch_sprint(self._selected_epic_index + 1)
        else:  # cards
            self._move_card_selection(4)

    def _enter_zone(self, zone: str) -> None:
        prev_zone = self._focus_zone
        self._focus_zone = zone
        # Sync header tab index to current active tab when entering header
        if zone == "header":
            _tab_name_to_id = {"sprint": "tab-sprint", "agents": "tab-agents", "history": "tab-history"}
            active_id = _tab_name_to_id.get(self._active_tab, "tab-sprint")
            self._header_tab_index = self._TAB_IDS.index(active_id) if active_id in self._TAB_IDS else 0
        # Always clear hover state when navigating by keyboard — selection is shown via -active classes
        self._cancel_hover_clear_timer()
        self._set_tab_hover(None)
        self._set_sprint_hover(None)
        self._set_card_hover(None)
        # De-highlight card when leaving cards zone
        if prev_zone == "cards" and zone != "cards":
            self._set_card_active(self._selected_story_id, False)
        # Re-highlight card when returning to cards zone
        if zone == "cards" and prev_zone != "cards":
            if self._selected_story_id:
                self._set_card_active(self._selected_story_id, True)
            else:
                stories = self._current_sprint_stories()
                if stories:
                    self._set_selected_story(stories[0].id)
        # Right zone: highlight the sidebar status selector
        self._set_sidebar_kb_focus(zone == "right")

    def _set_tab_hover_by_index(self, idx: int) -> None:
        # Only used for mouse hover; keyboard nav in header uses no hover highlight
        pass

    def _move_tab(self, delta: int) -> None:
        self._header_tab_index = max(0, min(len(self._TAB_IDS) - 1, self._header_tab_index + delta))
        _tab_actions = [self.action_tab_sprint, self.action_tab_agents, self.action_tab_history]
        _tab_actions[self._header_tab_index]()

    def _set_sidebar_kb_focus(self, active: bool) -> None:
        try:
            row = self.query_one("#sidebar-status-row")
            if active:
                row.add_class("-kb-focus")
            else:
                row.remove_class("-kb-focus")
        except Exception:
            pass

    # --- Phase banner (TUI-1 / TUI-14) ---

    def _update_phase_banner(self) -> None:
        try:
            banner = self.query_one("#phase-banner-text", Static)
        except Exception:
            return
        phase = project_phase(self._state)
        summary = _phase_summary(self._state)
        _phase_markup = {
            "retrospective":  "[bold yellow]★ retrospective[/bold yellow]",
            "planning":       "[bold blue]→ planning[/bold blue]",
            "analysis":       "[bold red]○ analysis[/bold red]",
        }
        phase_text = _phase_markup.get(phase, None)
        parts = []
        if phase_text:
            parts.append(phase_text)
        parts.append(f"{summary['active_epics']} active epics")
        if summary["in_review"]:
            parts.append(f"[bold magenta]{summary['in_review']} in review[/bold magenta]")
        if summary["pending_retros"]:
            parts.append(f"{summary['pending_retros']} retros pending")
        banner.update("  ·  ".join(parts))

    # --- Retrospective button ---

    def _epics_needing_retro(self) -> list:
        """Return epics where all stories done, retro not done, sprint still open."""
        result = []
        for epic in self._epics:
            if epic.status == "done":
                continue
            stories = [s for s in self._state.stories if str(s.epic_id) == str(epic.id)]
            if not stories:
                continue
            all_done = all(s.yaml_status == "done" for s in stories)
            retro = epic.retrospective_status
            retro_pending = retro not in ("done", None) or retro is None
            if all_done and (retro in (None, "required", "optional", "pending") or retro is None):
                result.append(epic)
        return result

    def _update_retro_btn(self) -> None:
        try:
            row = self.query_one("#retro-row")
        except Exception:
            return
        if not self._epics:
            row.display = False
            return
        epic = self._epics[self._selected_epic_index]
        stories = [s for s in self._state.stories if str(s.epic_id) == str(epic.id)]
        all_done = bool(stories) and all(s.yaml_status == "done" for s in stories)
        needs_retro = all_done and epic.status != "done" and epic.retrospective_status not in ("done",)
        row.display = needs_retro

    # --- Filter (TUI-16) ---

    def _set_filter(self, index: int) -> None:
        self._cancel_hover_clear_timer()
        self._filter_index = index % len(_FILTERS)
        self._status_filter = _FILTERS[self._filter_index]
        self._selected_story_id = None
        self._hovered_story_id = None
        self._render_cards()
        self._render_detail()
        label = self._status_filter or "all"
        self.notify(f"Filter: {label}", timeout=1.0)

    # --- Tab key shortcuts (TUI-11) ---

    def action_tab_sprint(self) -> None:
        self._render_home()

    def action_tab_agents(self) -> None:
        self.action_agents()

    def action_tab_workflows(self) -> None:
        self.action_workflows()

    def action_tab_history(self) -> None:
        self.action_history()

    def action_dev_session(self) -> None:
        """Launch a dev (Amelia) session directly, no story pre-load."""
        missing = check_prerequisites()
        if missing:
            self.notify(f"Missing: {', '.join(missing)} — install then retry", timeout=4.0)
            return
        self.notify("Starting dev session with Amelia…", timeout=2.0)
        state = self._state
        model = self.selected_model
        with self.app.suspend():
            entry = run_workflow(workflow_key="dev-story", state=state, model=model, story=None, from_menu=True, cli_tool=self._tui_config.cli_tool)

        def _on_done() -> None:
            self._state = load_state(self._project_root)
            self._epics = self._sorted_epics()
            self._render_home()
            self.notify("✓ Dev session ended — state reloaded", timeout=3.0)

        self._save_run_entry(entry, _on_done)

    # --- Help screen (TUI-15) ---

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_bmad_help(self) -> None:
        """Run bmad-help skill for context-aware assistance."""
        if "help" not in WORKFLOWS:
            self.notify("BMad Help workflow not available", severity="warning")
            return
        
        # Run the help workflow in interactive mode
        entry = run_workflow(
            workflow_key="help",
            state=self._state,
            model=self.selected_model,
            from_menu=True,  # Interactive mode
            cli_tool=self._tui_config.cli_tool,
        )
        if entry:
            append_history(self._project_root, entry)
            self._history_entries = list(reversed(load_history(self._project_root)))
        self.refresh(recompose=True)

    def action_search(self) -> None:
        history_entries = list(reversed(load_history(self._project_root)))

        def callback(result: tuple[str, str, str] | None) -> None:
            if result is None:
                return
            kind, key, _label = result
            if kind == "story":
                # Find and switch to the epic that owns this story
                story = next((s for s in self._state.stories if s.id == key), None)
                if story:
                    epic_index = next(
                        (i for i, e in enumerate(self._epics) if str(e.id) == str(story.epic_id)),
                        None,
                    )
                    if epic_index is not None and epic_index != self._selected_epic_index:
                        self._switch_sprint(epic_index)
                self._selected_story_id = key
                self._render_cards()
                self._render_detail()
            elif kind == "agent":
                self.action_agents()
            elif kind == "workflow":
                wf = WORKFLOWS.get(key)
                saved_model_str = self._tui_config.get_model_for(key, self.selected_model.value)
                try:
                    initial_model = Model(saved_model_str)
                except ValueError:
                    initial_model = wf.default_model if wf else self.selected_model
                self.push_screen(
                    WorkflowPickerModal(initial_workflow_key=key, initial_model=initial_model),
                    self._on_workflow_modal_result,
                )
            elif kind == "history":
                entry = next((e for e in history_entries if e.session_id == key), None)
                if entry is not None:
                    self._run_history_entry(entry)

        self.push_screen(SearchScreen(self._state.stories, history_entries, agents=load_agents(self._project_root)), callback)
