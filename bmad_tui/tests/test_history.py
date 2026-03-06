"""Tests for bmad_tui/history.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from bmad_tui.history import HistoryEntry, append_history, has_zero_code_changes, load_history, purge_legacy_entries, purge_trivial_entries, is_trivial_entry


def _make_entry(**kwargs) -> HistoryEntry:
    defaults = dict(
        ts="2026-03-04T17:30:00Z",
        workflow="dev-story",
        agent="bmad-agent-bmm-dev",
        model="claude-sonnet-4.6",
        story_id="3-6",
        epic_id="3",
        branch="feature/us3-6",
        session_id="",
        usage_est="",
        api_time="",
        session_time="",
        code_changes="",
    )
    defaults.update(kwargs)
    return HistoryEntry(**defaults)


class TestLoadHistory:
    def test_load_history_empty_when_no_file(self, tmp_path: Path) -> None:
        """Returns [] when log file does not exist."""
        result = load_history(tmp_path)
        assert result == []

    def test_load_history_reads_entries(self, tmp_path: Path) -> None:
        """Returns parsed HistoryEntry objects from JSONL."""
        entry = _make_entry()
        append_history(tmp_path, entry)
        result = load_history(tmp_path)
        assert len(result) == 1
        assert result[0].workflow == "dev-story"
        assert result[0].story_id == "3-6"

    def test_load_history_truncates_to_100(self, tmp_path: Path) -> None:
        """Returns only the last 100 entries when more exist."""
        for i in range(120):
            append_history(tmp_path, _make_entry(story_id=str(i)))
        result = load_history(tmp_path)
        assert len(result) == 100
        # Last 100: entries 20-119
        assert result[0].story_id == "20"
        assert result[-1].story_id == "119"

    def test_load_history_skips_malformed_lines(self, tmp_path: Path) -> None:
        """Malformed JSON lines are silently skipped."""
        log = tmp_path / "artifacts" / "logs" / "tui-history.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            '{"ts":"t","workflow":"w","agent":"a","model":"m","story_id":"s","epic_id":"e"}\n'
            'NOT_JSON\n'
            '\n'
            '{"ts":"t2","workflow":"w2","agent":"a","model":"m","story_id":"s2","epic_id":"e"}\n',
            encoding="utf-8",
        )
        result = load_history(tmp_path)
        assert len(result) == 2
        assert result[0].workflow == "w"
        assert result[1].workflow == "w2"


class TestAppendHistory:
    def test_append_history_creates_dir_and_file(self, tmp_path: Path) -> None:
        """Creates artifacts/logs/ and tui-history.jsonl if they don't exist."""
        entry = _make_entry()
        append_history(tmp_path, entry)
        log = tmp_path / "artifacts" / "logs" / "tui-history.jsonl"
        assert log.exists()

    def test_append_history_adds_entry(self, tmp_path: Path) -> None:
        """Each append_history call adds one line to the file."""
        append_history(tmp_path, _make_entry(story_id="1"))
        append_history(tmp_path, _make_entry(story_id="2"))
        result = load_history(tmp_path)
        assert len(result) == 2
        assert result[0].story_id == "1"
        assert result[1].story_id == "2"

    def test_session_id_roundtrip(self, tmp_path: Path) -> None:
        """session_id is persisted and loaded correctly."""
        uid = "99d8f74d-572d-4464-bef1-d658ec2ff8c3"
        append_history(tmp_path, _make_entry(session_id=uid))
        result = load_history(tmp_path)
        assert result[0].session_id == uid

    def test_session_id_defaults_to_empty_for_old_entries(self, tmp_path: Path) -> None:
        """Old JSONL entries without session_id load with empty string."""
        log = tmp_path / "artifacts" / "logs" / "tui-history.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            '{"ts":"t","workflow":"w","agent":"a","model":"m","story_id":"s","epic_id":"e"}\n',
            encoding="utf-8",
        )
        result = load_history(tmp_path)
        assert result[0].session_id == ""

    def test_session_stats_roundtrip(self, tmp_path: Path) -> None:
        """Session stats fields persist and load correctly."""
        entry = _make_entry(
            session_time="3h 53m 28s",
            code_changes="+86 -8",
            api_time="3s",
            usage_est="0 Premium requests",
        )
        append_history(tmp_path, entry)
        result = load_history(tmp_path)
        assert result[0].branch == "feature/us3-6"
        assert result[0].session_time == "3h 53m 28s"
        assert result[0].code_changes == "+86 -8"
        assert result[0].api_time == "3s"
        assert result[0].usage_est == "0 Premium requests"

    def test_stats_default_to_empty_for_old_entries(self, tmp_path: Path) -> None:
        """Old JSONL entries without stats fields load with empty strings."""
        log = tmp_path / "artifacts" / "logs" / "tui-history.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            '{"ts":"t","workflow":"w","agent":"a","model":"m","story_id":"s","epic_id":"e"}\n',
            encoding="utf-8",
        )
        result = load_history(tmp_path)
        assert result[0].session_time == ""
        assert result[0].code_changes == ""
        assert result[0].branch == ""

    def test_task_name_roundtrip(self, tmp_path: Path) -> None:
        """task_name is persisted and loaded correctly."""
        entry = _make_entry(task_name="Add Export Feature")
        append_history(tmp_path, entry)
        result = load_history(tmp_path)
        assert result[0].task_name == "Add Export Feature"

    def test_task_name_defaults_to_empty_for_old_entries(self, tmp_path: Path) -> None:
        """Old JSONL entries without task_name load with empty string."""
        log = tmp_path / "artifacts" / "logs" / "tui-history.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            '{"ts":"t","workflow":"dev-story","agent":"a","model":"m","story_id":"3-6","epic_id":"3"}\n',
            encoding="utf-8",
        )
        result = load_history(tmp_path)
        assert result[0].task_name == ""


class TestPurgeLegacyEntries:
    def test_removes_entries_without_session_id(self, tmp_path: Path) -> None:
        """Entries without session_id are removed."""
        append_history(tmp_path, _make_entry(story_id="old", session_id=""))
        append_history(tmp_path, _make_entry(story_id="new", session_id="aaaaaaaa-0000-0000-0000-000000000001"))
        removed = purge_legacy_entries(tmp_path)
        assert removed == 1
        result = load_history(tmp_path)
        assert len(result) == 1
        assert result[0].story_id == "new"

    def test_deletes_file_when_all_legacy(self, tmp_path: Path) -> None:
        """Log file is removed entirely if all entries are legacy."""
        append_history(tmp_path, _make_entry(session_id=""))
        purge_legacy_entries(tmp_path)
        log = tmp_path / "artifacts" / "logs" / "tui-history.jsonl"
        assert not log.exists()

    def test_returns_zero_when_nothing_to_purge(self, tmp_path: Path) -> None:
        """Returns 0 when all entries already have session_id."""
        uid = "aaaaaaaa-0000-0000-0000-000000000001"
        append_history(tmp_path, _make_entry(session_id=uid))
        assert purge_legacy_entries(tmp_path) == 0

    def test_no_op_when_no_file(self, tmp_path: Path) -> None:
        """Returns 0 and does not crash when history file is absent."""
        assert purge_legacy_entries(tmp_path) == 0


class TestIsTrivialEntry:
    def test_empty_api_and_changes_is_trivial(self):
        assert is_trivial_entry(_make_entry(api_time="", code_changes=""))

    def test_zero_api_time_is_trivial(self):
        assert is_trivial_entry(_make_entry(api_time="0s", code_changes=""))

    def test_zero_changes_plus_zero_api_is_trivial(self):
        assert is_trivial_entry(_make_entry(api_time="0s", code_changes="+0 -0"))

    def test_zero_api_time_is_trivial_even_with_old_code_changes(self):
        # Resumed session: api_time=0s but code_changes shows the original session's diff
        assert is_trivial_entry(_make_entry(api_time="0s", code_changes="+86 -8"))

    def test_nonzero_api_time_not_trivial(self):
        assert not is_trivial_entry(_make_entry(api_time="3s", code_changes=""))

    def test_empty_api_but_real_changes_not_trivial(self):
        # Stats not captured but real code changes exist — keep the entry
        assert not is_trivial_entry(_make_entry(api_time="", code_changes="+5 -2"))

    def test_real_session_not_trivial(self):
        assert not is_trivial_entry(_make_entry(api_time="3h 53m 28s", code_changes="+86 -8"))


class TestHasZeroCodeChanges:
    def test_empty_string_is_zero(self):
        assert has_zero_code_changes(_make_entry(code_changes=""))

    def test_plus_zero_minus_zero_is_zero(self):
        assert has_zero_code_changes(_make_entry(code_changes="+0 -0"))

    def test_string_zero_is_zero(self):
        assert has_zero_code_changes(_make_entry(code_changes="0"))

    def test_real_changes_not_zero(self):
        assert not has_zero_code_changes(_make_entry(code_changes="+5 -2"))

    def test_additions_only_not_zero(self):
        assert not has_zero_code_changes(_make_entry(code_changes="+86 -8"))

    def test_zero_independent_of_api_time(self):
        # has_zero_code_changes only inspects code_changes, not api_time
        assert has_zero_code_changes(_make_entry(api_time="3h 53m 28s", code_changes="+0 -0"))
        assert not has_zero_code_changes(_make_entry(api_time="", code_changes="+5 -2"))


class TestPurgeTrivialEntries:
    def test_removes_trivial_entries(self, tmp_path: Path) -> None:
        uid = "aaaaaaaa-0000-0000-0000-000000000001"
        append_history(tmp_path, _make_entry(session_id=uid, api_time="0s", code_changes=""))
        append_history(tmp_path, _make_entry(session_id=uid, api_time="5s", code_changes="+3 -1"))
        removed = purge_trivial_entries(tmp_path)
        assert removed == 1
        assert len(load_history(tmp_path)) == 1

    def test_deletes_file_when_all_trivial(self, tmp_path: Path) -> None:
        uid = "aaaaaaaa-0000-0000-0000-000000000001"
        append_history(tmp_path, _make_entry(session_id=uid, api_time="", code_changes=""))
        purge_trivial_entries(tmp_path)
        assert not (tmp_path / "artifacts" / "logs" / "tui-history.jsonl").exists()

    def test_no_op_when_no_file(self, tmp_path: Path) -> None:
        assert purge_trivial_entries(tmp_path) == 0

    def test_keeps_good_entries(self, tmp_path: Path) -> None:
        uid = "aaaaaaaa-0000-0000-0000-000000000001"
        append_history(tmp_path, _make_entry(session_id=uid, api_time="10s", code_changes="+1 -0"))
        assert purge_trivial_entries(tmp_path) == 0
        assert len(load_history(tmp_path)) == 1
