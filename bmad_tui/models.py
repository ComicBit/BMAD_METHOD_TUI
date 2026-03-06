"""Core data models for the BMAD Dashboard TUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Model(str, Enum):
    SONNET = "claude-sonnet-4.6"
    OPUS = "claude-opus-4.6"
    CODEX = "gpt-5.3-codex"

    def label(self) -> str:
        return {
            Model.SONNET: "sonnet-4.6",
            Model.OPUS: "opus-4.6",
            Model.CODEX: "codex-5.3",
        }[self]


class StoryStatus(str, Enum):
    NEEDS_STORY = "needs-story"       # backlog + no .md file
    READY_FOR_DEV = "ready-for-dev"
    IN_PROGRESS = "in-progress"
    REVIEW = "review"
    DONE = "done"
    BACKLOG = "backlog"               # backlog + file exists
    BLOCKED = "blocked"
    UNKNOWN = "unknown"

    @property
    def badge_label(self) -> str:
        # Returns the raw YAML key string (e.g., "needs-story"), not a display label.
        return {
            StoryStatus.NEEDS_STORY: "needs-story",
            StoryStatus.READY_FOR_DEV: "ready-for-dev",
            StoryStatus.IN_PROGRESS: "in-progress",
            StoryStatus.REVIEW: "review",
            StoryStatus.DONE: "done",
            StoryStatus.BACKLOG: "backlog",
            StoryStatus.BLOCKED: "blocked",
            StoryStatus.UNKNOWN: "unknown",
        }[self]

    @property
    def emoji(self) -> str:
        """Unicode symbol for this status (terminal-safe, consistent with _BADGE in dashboard.py)."""
        return {
            StoryStatus.NEEDS_STORY:   "○",
            StoryStatus.READY_FOR_DEV: "●",
            StoryStatus.IN_PROGRESS:   "◆",
            StoryStatus.REVIEW:        "◈",
            StoryStatus.DONE:          "✓",
            StoryStatus.BACKLOG:       "·",
            StoryStatus.BLOCKED:       "⊘",
            StoryStatus.UNKNOWN:       "?",
        }[self]


# Rich markup pill badges for all story statuses. Key: "status_badges"
STATUS_BADGES: dict[StoryStatus, str] = {
    StoryStatus.NEEDS_STORY:   "[bold #ff6b6b]○ needs-story[/]",
    StoryStatus.READY_FOR_DEV: "[bold #50fa7b]● ready[/]",
    StoryStatus.IN_PROGRESS:   "[bold #8be9fd]◆ in-progress[/]",
    StoryStatus.REVIEW:        "[bold #bd93f9]◈ review[/]",
    StoryStatus.BLOCKED:       "[bold #ff5555 on #44001a]⊘ blocked[/]",
    StoryStatus.DONE:          "[#6272a4]✓ done[/]",
    StoryStatus.BACKLOG:       "[#6272a4]· backlog[/]",
    StoryStatus.UNKNOWN:       "[#6272a4]? unknown[/]",
}


@dataclass
class Story:
    id: str                   # e.g. "3-5c"
    yaml_status: str          # raw value from sprint-status.yaml
    epic_id: str              # e.g. "3"
    file_path: Path | None    # None if story .md doesn't exist yet
    blocked: bool = False     # derived from epic prerequisite marker

    @property
    def short_id(self) -> str:
        """Short display ID like '7-5' or '3-5c' (first two dash-segments)."""
        parts = self.id.split("-")
        return "-".join(parts[:2]) if len(parts) >= 2 else self.id

    @property
    def doc_title(self) -> str:
        """Title from the story .md file's first `#` heading, falling back to id-derived title."""
        if self.file_path is None:
            return self.title
        try:
            for line in Path(self.file_path).open():
                line = line.strip()
                if line.startswith("# "):
                    return line[2:].strip()
        except OSError:
            pass
        return self.title

    @property
    def title(self) -> str:
        # id format: "{epic}-{story_num}-{title-word}-{title-word}..."
        # e.g. "7-5-bundled-model-bootstrap" → skip first 2 segments
        parts = self.id.split("-")
        if len(parts) > 2:
            return " ".join(w.capitalize() for w in parts[2:])
        return self.id

    @property
    def effective_status(self) -> StoryStatus:
        if self.yaml_status == "backlog":
            return StoryStatus.READY_FOR_DEV if self.file_path else StoryStatus.NEEDS_STORY
        mapping = {
            "ready-for-dev": StoryStatus.READY_FOR_DEV,
            "in-progress": StoryStatus.IN_PROGRESS,
            "review": StoryStatus.REVIEW,
            "done": StoryStatus.DONE,
            "blocked": StoryStatus.BLOCKED,
        }
        return mapping.get(self.yaml_status, StoryStatus.UNKNOWN)

    @property
    def primary_workflow(self) -> str | None:
        """Key into WORKFLOWS for the primary action for this story."""
        return {
            StoryStatus.NEEDS_STORY: "create-story",
            StoryStatus.READY_FOR_DEV: "dev-story",
            StoryStatus.IN_PROGRESS: "dev-story",
            StoryStatus.REVIEW: "code-review",
            StoryStatus.BACKLOG: "dev-story",
            StoryStatus.DONE: None,
            StoryStatus.BLOCKED: None,
            StoryStatus.UNKNOWN: None,
        }.get(self.effective_status)


@dataclass
class Epic:
    id: str           # e.g. "3"
    status: str       # raw from yaml: backlog / in-progress / done
    title: str = ""   # from epics.md e.g. "Audio Capture & Session Persistence"
    blocked: bool = False
    retrospective_status: str | None = None   # done / required / None
    stories: list[Story] = field(default_factory=list)

    @property
    def progress_icon(self) -> str:
        if self.status == "done":
            return "✓"
        if self.status == "in-progress":
            return "→"
        return "○"

    @property
    def rich_style(self) -> str:
        if self.status == "done":
            return "#50fa7b"
        if self.status == "in-progress":
            return "#8be9fd"
        return "#6272a4"


@dataclass
class WorkflowDef:
    label: str
    agent: str
    persona: str
    default_model: Model
    prompt_template: str
    model_locked: bool = False
    description: str = ""
    bmad_phase: str = "Implementation"


@dataclass
class AgentDef:
    name: str            # e.g. "Winston"
    persona: str         # e.g. "Winston (Architect) 🏗️"
    icon: str            # e.g. "🏗️"
    workflow_keys: list[str]
    role: str = ""       # e.g. "Architect"
    description: str = ""  # Short description of what this agent does
    category: str = "sprint"   # "sprint" (bmm/tea) or "other" (bmb/cis/core/…)
    agent_id: str = ""         # CLI agent ID, e.g. "bmad-agent-bmm-dev"


@dataclass
class ProjectState:
    epics: list[Epic]
    stories: list[Story]
    project_root: Path
    sprint_status_path: Path
    yaml_error: str | None = None

    def actionable_stories(self) -> list[Story]:
        """Stories that are not done, sorted by urgency."""
        priority = [
            StoryStatus.REVIEW,
            StoryStatus.IN_PROGRESS,
            StoryStatus.READY_FOR_DEV,
            StoryStatus.NEEDS_STORY,
            StoryStatus.BACKLOG,
            StoryStatus.BLOCKED,
            StoryStatus.UNKNOWN,
            StoryStatus.DONE,
        ]
        return sorted(
            self.stories,
            key=lambda s: priority.index(s.effective_status),
        )
