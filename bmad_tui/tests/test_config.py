"""Tests for bmad_tui/config.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from bmad_tui.config import TuiConfig, load_config, save_config
from bmad_tui.models import Model


class TestLoadConfig:
    def test_load_config_returns_default_when_no_file(self, tmp_path: Path) -> None:
        """Returns empty TuiConfig when config file does not exist."""
        config = load_config(tmp_path)
        assert config.workflow_models == {}

    def test_load_config_reads_workflow_models(self, tmp_path: Path) -> None:
        """Reads workflow_models from JSON file."""
        cfg = TuiConfig(workflow_models={"dev-story": Model.OPUS.value})
        save_config(tmp_path, cfg)
        loaded = load_config(tmp_path)
        assert loaded.workflow_models["dev-story"] == Model.OPUS.value

    def test_load_config_skips_malformed_json(self, tmp_path: Path) -> None:
        """Returns empty TuiConfig when JSON is malformed."""
        (tmp_path / ".bmad-tui-config.json").write_text("NOT_JSON", encoding="utf-8")
        config = load_config(tmp_path)
        assert config.workflow_models == {}


class TestSaveConfig:
    def test_save_config_round_trip(self, tmp_path: Path) -> None:
        """Save then load returns identical TuiConfig."""
        original = TuiConfig(workflow_models={"code-review": Model.SONNET.value})
        save_config(tmp_path, original)
        loaded = load_config(tmp_path)
        assert loaded.workflow_models == original.workflow_models

    def test_save_config_overwrites_existing(self, tmp_path: Path) -> None:
        """Second save replaces the first."""
        save_config(tmp_path, TuiConfig(workflow_models={"dev-story": Model.SONNET.value}))
        save_config(tmp_path, TuiConfig(workflow_models={"dev-story": Model.OPUS.value}))
        loaded = load_config(tmp_path)
        assert loaded.workflow_models["dev-story"] == Model.OPUS.value


class TestTuiConfigMethods:
    def test_get_model_for_returns_remembered(self) -> None:
        """Returns remembered model value for known workflow key."""
        cfg = TuiConfig(workflow_models={"dev-story": Model.OPUS.value})
        assert cfg.get_model_for("dev-story", Model.SONNET.value) == Model.OPUS.value

    def test_get_model_for_returns_fallback_when_unknown(self) -> None:
        """Returns fallback when workflow key has no remembered model."""
        cfg = TuiConfig()
        assert cfg.get_model_for("code-review", Model.SONNET.value) == Model.SONNET.value

    def test_set_model_for_stores_value(self) -> None:
        """set_model_for updates workflow_models in place."""
        cfg = TuiConfig()
        cfg.set_model_for("dev-story", Model.OPUS.value)
        assert cfg.workflow_models["dev-story"] == Model.OPUS.value


class TestAutoDespawn:
    def test_default_is_true(self) -> None:
        assert TuiConfig().auto_despawn_yolo is True

    def test_round_trip_false(self, tmp_path: Path) -> None:
        cfg = TuiConfig(auto_despawn_yolo=False)
        save_config(tmp_path, cfg)
        assert load_config(tmp_path).auto_despawn_yolo is False

    def test_round_trip_true(self, tmp_path: Path) -> None:
        cfg = TuiConfig(auto_despawn_yolo=True)
        save_config(tmp_path, cfg)
        assert load_config(tmp_path).auto_despawn_yolo is True

    def test_old_config_without_key_defaults_to_true(self, tmp_path: Path) -> None:
        """Configs written before auto_despawn_yolo was added default to True."""
        import json
        (tmp_path / ".bmad-tui-config.json").write_text(
            json.dumps({"workflow_models": {}}), encoding="utf-8"
        )
        assert load_config(tmp_path).auto_despawn_yolo is True
