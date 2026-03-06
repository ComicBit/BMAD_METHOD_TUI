"""Parse sprint-status.yaml and scan story files to build ProjectState."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .models import Epic, ProjectState, Story


_EPIC_KEY_RE = re.compile(r"^epic-\d+$")
_EPIC_RETRO_RE = re.compile(r"^epic-\d+-retrospective$")
_EPIC_META_RE = re.compile(r"^epic-\d+-.+$")  # prerequisite, governance, etc.
_STORY_ID_RE = re.compile(r"^(\d+)-(.+)$")    # e.g. "3-5c", "7-6"


def _epic_id_from_story(story_id: str) -> str:
    """Return the epic number from a story key like '3-5c' → '3'."""
    m = _STORY_ID_RE.match(story_id)
    return m.group(1) if m else "?"


_EPIC_TITLE_RE = re.compile(r"^##\s+Epic\s+(\d+):\s*(.+)$")


def _load_epic_titles(project_root: Path) -> dict[str, str]:
    """Parse epics.md and return {epic_id: title_string}."""
    epics_md = project_root / "_bmad-output" / "planning-artifacts" / "epics.md"
    titles: dict[str, str] = {}
    try:
        for line in epics_md.read_text().splitlines():
            m = _EPIC_TITLE_RE.match(line.strip())
            if m:
                titles[m.group(1)] = m.group(2).strip()
    except OSError:
        pass
    return titles


def _find_story_file(story_id: str, artifacts_dir: Path) -> Path | None:
    """Find a story file matching the story ID (exact match, then glob fallback)."""
    exact = artifacts_dir / f"{story_id}.md"
    if exact.exists():
        return exact
    matches = list(artifacts_dir.glob(f"{story_id}-*.md"))
    return matches[0] if matches else None


def load_state(project_root: Path) -> ProjectState:
    """Load full project state from sprint-status.yaml and the filesystem."""
    artifacts_dir = project_root / "_bmad-output" / "implementation-artifacts"
    sprint_status_path = artifacts_dir / "sprint-status.yaml"

    if not sprint_status_path.exists():
        return ProjectState(
            epics=[],
            stories=[],
            project_root=project_root,
            sprint_status_path=sprint_status_path,
        )

    try:
        raw = yaml.safe_load(sprint_status_path.read_text())
        dev_status: dict = raw.get("development_status", {})
    except yaml.YAMLError as exc:
        return ProjectState(
            epics=[],
            stories=[],
            project_root=project_root,
            sprint_status_path=sprint_status_path,
            yaml_error=str(exc),
        )

    epics: dict[str, Epic] = {}
    blocked_epics: set[str] = set()
    stories: list[Story] = []

    # First pass: collect epic statuses, retrospective statuses, and blocked markers
    retro_statuses: dict[str, str] = {}
    for key, value in dev_status.items():
        if _EPIC_KEY_RE.match(key):
            epic_id = key.split("-")[1]
            epics[epic_id] = Epic(id=epic_id, status=str(value))
        elif _EPIC_RETRO_RE.match(key):
            epic_id = key.split("-")[1]
            retro_statuses[epic_id] = str(value)
        elif _EPIC_META_RE.match(key) and "prerequisite" in key:
            epic_id = key.split("-")[1]
            blocked_epics.add(epic_id)

    # Apply retrospective statuses to epic objects
    for epic_id, retro_status in retro_statuses.items():
        if epic_id in epics:
            epics[epic_id].retrospective_status = retro_status

    # Apply titles from epics.md
    epic_titles = _load_epic_titles(project_root)
    for epic_id, title in epic_titles.items():
        if epic_id in epics:
            epics[epic_id].title = title

    # Second pass: collect stories
    for key, value in dev_status.items():
        if _EPIC_KEY_RE.match(key) or _EPIC_RETRO_RE.match(key) or _EPIC_META_RE.match(key):
            continue
        if not _STORY_ID_RE.match(key):
            continue

        epic_id = _epic_id_from_story(key)
        file_path = _find_story_file(key, artifacts_dir)
        blocked = epic_id in blocked_epics and str(value) in ("backlog", "ready-for-dev")

        story = Story(
            id=key,
            yaml_status=str(value),
            epic_id=epic_id,
            file_path=file_path,
            blocked=blocked,
        )
        stories.append(story)

        if epic_id in epics:
            epics[epic_id].stories.append(story)
            if epic_id in blocked_epics:
                epics[epic_id].blocked = True

    return ProjectState(
        epics=list(epics.values()),
        stories=stories,
        project_root=project_root,
        sprint_status_path=sprint_status_path,
    )


def project_phase(state: ProjectState) -> str:
    """Return the current project phase based on state.

    Priority (first match wins):
    1. No PRD file → "analysis"
    2. PRD + architecture present, no stories/epics → "planning"
    3. Any story in-progress or review → "implementation"
    4. All stories done, any epic has pending retro → "retrospective"
    5. Otherwise → "complete"
    """
    prd_path = state.project_root / "_bmad-output" / "planning-artifacts" / "prd.md"
    arch_path = state.project_root / "_bmad-output" / "planning-artifacts" / "architecture.md"

    if not prd_path.exists():
        return "analysis"

    if arch_path.exists() and not state.stories and not state.epics:
        return "planning"

    for story in state.stories:
        if story.yaml_status in ("in-progress", "review"):
            return "implementation"

    if state.stories and all(s.yaml_status == "done" for s in state.stories):
        for epic in state.epics:
            if epic.retrospective_status and epic.retrospective_status != "done":
                return "retrospective"
        return "complete"

    return "complete"


def _phase_summary(state: ProjectState) -> dict:
    """Return counts for the phase banner: active_epics, in_review, pending_retros, pending_retro_ids."""
    active_epics = sum(1 for e in state.epics if e.status == "in-progress")
    in_review = sum(1 for s in state.stories if s.yaml_status == "review")
    pending_retro_ids = [
        e.id for e in state.epics
        if e.retrospective_status and e.retrospective_status != "done"
    ]
    return {
        "active_epics": active_epics,
        "in_review": in_review,
        "pending_retros": len(pending_retro_ids),  # backward compat
        "pending_retro_ids": pending_retro_ids,
    }


def find_project_root(start: Path | None = None) -> Path:
    """Walk up from start (or cwd) to find the git root."""
    current = (start or Path.cwd()).resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
        if (parent / "_bmad").exists():
            return parent
    return current
