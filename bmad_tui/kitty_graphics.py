"""Terminal icon helpers for inline agent icons in the TUI.

Primary renderer: chafa (symbol/block output).
Fallback: plain emoji icon text.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


_NEW_ASSETS_DIR = Path(__file__).parent / "assets" / "new"
_LEGACY_ASSETS_DIR = Path(__file__).parent / "assets" / "agent-icons"

_ICON_FILES = {
    "bob": "men_running.png",
    "amelia": "laptop.png",
    "winston": "builder.png",
    "mary": "stocks.png",
    "john": "notebook.png",
    "sally": "art.png",
    "quinn": "science.png",
    "murat": "science.png",
    "paige": "books.png",
    "barry": "rocket.png",
    "creative & meta": "art.png",
}


def _supports_chafa() -> bool:
    if os.environ.get("BMAD_TUI_DISABLE_CHAFA") == "1":
        return False
    return shutil.which("chafa") is not None


def _icon_path(agent_name: str) -> Path | None:
    file_name = _ICON_FILES.get(agent_name.lower())
    if not file_name:
        return None
    preferred = _NEW_ASSETS_DIR / file_name
    if preferred.exists():
        return preferred
    legacy = _LEGACY_ASSETS_DIR / file_name
    return legacy if legacy.exists() else None


def _render_with_chafa(path: Path, cols: int, rows: int) -> str | None:
    """Render a PNG to terminal block/symbol art via chafa."""
    try:
        proc = subprocess.run(
            [
                "chafa",
                "--format=symbols",
                f"--size={cols}x{rows}",
                "--symbols=block",
                "--colors=none",
                "--animate=off",
                "--polite=on",
                "--relative=off",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        out = proc.stdout.strip("\n")
        return out if proc.returncode == 0 and out else None
    except Exception:
        return None


@lru_cache(maxsize=64)
def _icon_sequence(agent_name: str, cols: int, rows: int) -> str | None:
    path = _icon_path(agent_name)
    if path is None:
        return None
    return _render_with_chafa(path, cols=cols, rows=rows)


def render_agent_icon(agent_name: str, fallback: str, cols: int = 4, rows: int = 2) -> str:
    """Return terminal symbol art when chafa is available, else emoji fallback."""
    if not _supports_chafa():
        return fallback
    seq = _icon_sequence(agent_name, cols, rows)
    return seq if seq else fallback
