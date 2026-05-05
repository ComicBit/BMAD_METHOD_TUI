"""Fetch available models and effort levels from installed CLI harnesses.

Reads from local bundle files — no API calls.
- copilot: parses ~/.copilot/pkg/universal/<version>/app.js
- claude:  parses strings from the claude binary
- codex:   reads ~/.codex/config.toml + known static list
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


# Effort levels per harness, ordered low → high
EFFORT_LEVELS: dict[str, list[str]] = {
    "copilot": ["low", "medium", "high", "xhigh"],
    "claude":  ["low", "medium", "high", "xhigh", "max"],
    "codex":   ["low", "medium", "high"],
    "":        ["low", "medium", "high", "xhigh", "max"],
}

DEFAULT_EFFORT: dict[str, str] = {
    "copilot": "medium",
    "claude":  "medium",
    "codex":   "medium",
    "":        "medium",
}

# Rich-markup colors for effort levels (semaphore: green → red)
EFFORT_RICH: dict[str, str] = {
    "low":    "#50fa7b",   # green
    "medium": "#f1fa8c",   # yellow
    "high":   "#ffb86c",   # orange
    "xhigh":  "#ff5555",   # red
    "max":    "#ff5555",   # red
}


@dataclass
class ModelInfo:
    id: str
    label: str
    tier: str = "standard"   # fast/cheap | standard | premium


def effort_rich(effort: str) -> str:
    """Return Rich markup for an effort level badge, e.g. '[#f1fa8c]medium[/]'."""
    color = EFFORT_RICH.get(effort, "#f8f8f2")
    return f"[{color}]{effort}[/]"


# ── copilot ──────────────────────────────────────────────────────────────────

def _tier_from_name(model_id: str) -> str:
    low_hints  = {"-mini", "-nano", "-fast", "haiku", "gpt-5-mini", "gpt-5.4-mini", "gpt-5.1-codex-mini"}
    high_hints = {"opus", "gpt-5.4", "goldeneye", "gpt-5.1-codex-max", "premium"}
    for h in low_hints:
        if h in model_id:
            return "fast/cheap"
    for h in high_hints:
        if h in model_id:
            return "premium"
    return "standard"


def _fetch_copilot_models() -> list[ModelInfo]:
    pkg_dir = Path.home() / ".copilot" / "pkg" / "universal"
    if not pkg_dir.exists():
        return []
    def _semver(d: "Path") -> "tuple[int, ...]":
        try:
            return tuple(int(x) for x in d.name.split("."))
        except ValueError:
            return (0,)
    versions = sorted((d for d in pkg_dir.iterdir() if d.is_dir()), key=_semver, reverse=True)
    if not versions:
        return []
    app_js = versions[0] / "app.js"
    if not app_js.exists():
        return []

    content = app_js.read_text(errors="replace")

    # C_=["id1","id2",...] — the canonical available-model list
    m = re.search(r'\bC_=\[([^\]]+)\]', content)
    if not m:
        return []
    model_ids = re.findall(r'"([^"]+)"', m.group(1))

    # Kmt=new Set([...]) — hidden/restricted models to exclude
    m2 = re.search(r'\bKmt=new Set\(\[([^\]]*)\]\)', content)
    hidden = set(re.findall(r'"([^"]+)"', m2.group(1))) if m2 else set()

    return [
        ModelInfo(id=mid, label=mid, tier=_tier_from_name(mid))
        for mid in model_ids
        if mid not in hidden
    ]


# ── claude ────────────────────────────────────────────────────────────────────

def _fetch_claude_models() -> list[ModelInfo]:
    versions_dir = Path.home() / ".local" / "share" / "claude" / "versions"
    if not versions_dir.exists():
        return _fallback_claude()

    binaries = sorted(versions_dir.iterdir(), key=lambda f: f.name, reverse=True)
    if not binaries:
        return _fallback_claude()

    try:
        result = subprocess.run(
            ["strings", str(binaries[0])],
            capture_output=True, text=True, check=False, timeout=5,
        )
    except Exception:
        return _fallback_claude()

    seen: set[str] = set()
    by_family: dict[str, list[str]] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        # Match clean IDs like claude-sonnet-4-6 (no date suffix, no regex chars)
        if re.match(r'^claude-(sonnet|opus|haiku)-\d+(?:-\d+)*$', line) and line not in seen:
            seen.add(line)
            family = line.split("-")[1]  # sonnet / opus / haiku
            by_family.setdefault(family, []).append(line)

    # For each family: prefer clean IDs (no date suffix), then newest by version number
    models: list[ModelInfo] = []
    for family in ("opus", "sonnet", "haiku"):
        candidates = by_family.get(family, [])
        if not candidates:
            continue
        # Prefer IDs without date suffixes (no trailing -20XXXXXX pattern)
        clean = [mid for mid in candidates if not re.search(r"-20\d{6,}", mid)]
        pool = clean if clean else candidates
        # Sort by numeric version descending (e.g. 4-7 > 4-6 > 4-5)
        pool_sorted = sorted(pool, key=lambda s: [int(x) for x in re.findall(r"\d+", s) if int(x) < 100], reverse=True)
        mid = pool_sorted[0]
        tier = {"opus": "premium", "haiku": "fast/cheap"}.get(family, "standard")
        models.append(ModelInfo(id=mid, label=mid, tier=tier))

    return models if models else _fallback_claude()


def _fallback_claude() -> list[ModelInfo]:
    return [
        ModelInfo("claude-opus-4-7",   "claude-opus-4-7",   "premium"),
        ModelInfo("claude-sonnet-4-6",  "claude-sonnet-4-6",  "standard"),
        ModelInfo("claude-haiku-4-5",   "claude-haiku-4-5",   "fast/cheap"),
    ]


# ── codex ─────────────────────────────────────────────────────────────────────

_CODEX_STATIC: list[ModelInfo] = [
    ModelInfo("o4-mini", "o4-mini", "standard"),
    ModelInfo("o3",      "o3",      "premium"),
    ModelInfo("gpt-4.1", "gpt-4.1", "standard"),
    ModelInfo("gpt-4o",  "gpt-4o",  "standard"),
]


def _fetch_codex_models() -> list[ModelInfo]:
    config = Path.home() / ".codex" / "config.toml"
    current_id = ""
    if config.exists():
        try:
            text = config.read_text()
            m = re.search(r'^model\s*=\s*"([^"]+)"', text, re.MULTILINE)
            if m:
                current_id = m.group(1)
        except Exception:
            pass

    models = list(_CODEX_STATIC)
    if current_id and not any(m.id == current_id for m in models):
        tier = "premium" if current_id in ("o3", "o1") else "standard"
        models.insert(0, ModelInfo(current_id, current_id, tier))
    elif current_id:
        # Move to front
        models = [m for m in models if m.id != current_id]
        src = next(m for m in _CODEX_STATIC if m.id == current_id) if any(m.id == current_id for m in _CODEX_STATIC) else ModelInfo(current_id, current_id, "standard")
        models.insert(0, src)

    return models


# ── public API ────────────────────────────────────────────────────────────────

def fetch_models(cli_tool: str) -> list[ModelInfo]:
    """Return available models for the given harness (reads local files, no API)."""
    if cli_tool == "copilot":
        result = _fetch_copilot_models()
        return result or _fallback_copilot()
    if cli_tool == "claude":
        return _fetch_claude_models()
    if cli_tool == "codex":
        return _fetch_codex_models()
    # Unknown/empty harness: return all known
    return _fallback_copilot() + _fallback_claude() + _fetch_codex_models()


def _fallback_copilot() -> list[ModelInfo]:
    return [
        ModelInfo("gpt-5.3-codex", "gpt-5.3-codex", "standard"),
        ModelInfo("gpt-5.4",       "gpt-5.4",        "premium"),
        ModelInfo("gpt-5.4-mini",  "gpt-5.4-mini",   "fast/cheap"),
        ModelInfo("gpt-4.1",       "gpt-4.1",        "standard"),
        ModelInfo("claude-sonnet-4.6", "claude-sonnet-4.6", "standard"),
        ModelInfo("claude-opus-4.6",   "claude-opus-4.6",   "premium"),
    ]
