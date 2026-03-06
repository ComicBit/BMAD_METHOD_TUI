"""Persistent per-workflow model memory for the BMAD TUI."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

_CONFIG_FILENAME = ".bmad-tui-config.json"


@dataclass
class TuiConfig:
    """Small TUI preferences persisted to {project_root}/.bmad-tui-config.json."""

    workflow_models: dict[str, str] = field(default_factory=dict)
    # maps workflow_key (e.g. "dev-story") → Model.value (e.g. "claude-opus-4.6")

    # When True, yolo-mode agents are automatically killed after they complete
    # (idle timer fires once the task-done chime plays and a worktree change is detected).
    auto_despawn_yolo: bool = True

    # CLI tool to use for agent sessions: "copilot" | "claude" | "" (not yet chosen).
    cli_tool: str = ""

    def get_model_for(self, workflow_key: str, fallback: str) -> str:
        """Return the remembered model value for workflow_key, or fallback."""
        return self.workflow_models.get(workflow_key, fallback)

    def set_model_for(self, workflow_key: str, model_value: str) -> None:
        """Remember model_value for workflow_key."""
        self.workflow_models[workflow_key] = model_value


def _config_path(project_root: Path) -> Path:
    return project_root / _CONFIG_FILENAME


def load_config(project_root: Path) -> TuiConfig:
    """Load TuiConfig from {project_root}/.bmad-tui-config.json.

    Returns an empty TuiConfig if the file does not exist or is malformed.
    """
    path = _config_path(project_root)
    if not path.exists():
        return TuiConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return TuiConfig(
            workflow_models=data.get("workflow_models", {}),
            auto_despawn_yolo=bool(data.get("auto_despawn_yolo", True)),
            cli_tool=str(data.get("cli_tool", "")),
        )
    except (json.JSONDecodeError, TypeError, AttributeError):
        return TuiConfig()


def save_config(project_root: Path, config: TuiConfig) -> None:
    """Persist TuiConfig to {project_root}/.bmad-tui-config.json."""
    path = _config_path(project_root)
    path.write_text(
        json.dumps(
            {
                "workflow_models": config.workflow_models,
                "auto_despawn_yolo": config.auto_despawn_yolo,
                "cli_tool": config.cli_tool,
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
