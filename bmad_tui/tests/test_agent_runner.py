"""Tests for bmad_tui/agent_runner.py."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from bmad_tui.agent_runner import check_prerequisites, run_workflow, _extract_session_id, _extract_session_info, _find_latest_session_id
from bmad_tui.models import Model, ProjectState, Story
from bmad_tui.workflows import WORKFLOWS


# ── Fixtures ──────────────────────────────────────────────────────────────

def _make_story(
    id: str = "7-5-bundled-model",
    yaml_status: str = "review",
    file_path: Path | None = None,
) -> Story:
    return Story(id=id, yaml_status=yaml_status, epic_id=id.split("-")[0], file_path=file_path)


def _make_state(tmp_path: Path, story: Story | None = None) -> ProjectState:
    return ProjectState(
        epics=[],
        stories=[story] if story else [],
        project_root=tmp_path,
        sprint_status_path=tmp_path / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml",
    )


# ── check_prerequisites ───────────────────────────────────────────────────

class TestCheckPrerequisites:
    def test_all_present_returns_empty_list(self):
        with patch("shutil.which", return_value="/usr/bin/copilot"):
            missing = check_prerequisites()
        assert missing == []

    def test_copilot_missing_but_claude_present_is_ok(self):
        def fake_which(cmd):
            return None if cmd == "copilot" else "/usr/bin/x"
        with patch("shutil.which", side_effect=fake_which):
            missing = check_prerequisites()
        assert missing == []

    def test_expect_missing(self):
        def fake_which(cmd):
            return None if cmd == "expect" else "/usr/bin/copilot"
        with patch("shutil.which", side_effect=fake_which):
            missing = check_prerequisites()
        assert "expect" in missing

    def test_both_missing(self):
        with patch("shutil.which", return_value=None):
            missing = check_prerequisites()
        assert "copilot or claude" in missing
        assert "expect" in missing

    def test_returns_list_type(self):
        with patch("shutil.which", return_value="/usr/bin/x"):
            result = check_prerequisites()
        assert isinstance(result, list)


# ── run_workflow ──────────────────────────────────────────────────────────

class TestRunWorkflow:
    def _fake_which(self, cmd):
        return f"/usr/bin/{cmd}"

    def _call_run(self, workflow_key: str, story: Story | None, model: Model, tmp_path: Path):
        state = _make_state(tmp_path, story)
        captured: list[list] = []
        def fake_cleanup(cmd, cli_tool="copilot"):
            captured.append(list(cmd))
        with patch("shutil.which", side_effect=self._fake_which), \
             patch("bmad_tui.agent_runner._run_and_cleanup", side_effect=fake_cleanup), \
             patch("subprocess.run", return_value=MagicMock(stdout="abc\n", returncode=0)):
            run_workflow(workflow_key, state, model, story=story)
        return captured

    @staticmethod
    def _expect_call_args(captured: list[list]) -> list:
        """Return the arg list of the expect command."""
        for cmd in captured:
            if cmd and cmd[0] == "expect":
                return cmd
        return captured[0] if captured else []

    def test_dev_story_passes_sonnet_model(self, tmp_path):
        story = _make_story(id="3-5c-utterance", yaml_status="ready-for-dev",
                             file_path=tmp_path / "story.md")
        captured = self._call_run("dev-story", story, Model.SONNET, tmp_path)
        call_args = self._expect_call_args(captured)
        assert Model.SONNET.value in call_args

    def test_code_review_always_uses_codex_regardless_of_model_arg(self, tmp_path):
        story = _make_story(file_path=tmp_path / "story.md")
        captured = self._call_run("code-review", story, Model.SONNET, tmp_path)
        call_args = self._expect_call_args(captured)
        assert Model.CODEX.value in call_args
        assert Model.SONNET.value not in call_args

    def test_run_invokes_expect_script(self, tmp_path):
        story = _make_story(file_path=tmp_path / "story.md")
        captured = self._call_run("dev-story", story, Model.SONNET, tmp_path)
        call_args = self._expect_call_args(captured)
        cmd_str = " ".join(str(a) for a in call_args)
        assert "expect" in call_args[0] or "session.expect" in cmd_str

    def test_run_passes_project_root(self, tmp_path):
        story = _make_story(file_path=tmp_path / "story.md")
        captured = self._call_run("dev-story", story, Model.SONNET, tmp_path)
        call_args = self._expect_call_args(captured)
        assert str(tmp_path) in call_args

    def test_cr_idle_secs_is_90(self, tmp_path):
        story = _make_story(file_path=tmp_path / "story.md")
        captured = self._call_run("code-review", story, Model.CODEX, tmp_path)
        call_args = self._expect_call_args(captured)
        assert "90" in call_args

    def test_dev_story_idle_secs_is_180(self, tmp_path):
        story = _make_story(id="3-5c-ux", yaml_status="ready-for-dev",
                             file_path=tmp_path / "story.md")
        captured = self._call_run("dev-story", story, Model.SONNET, tmp_path)
        call_args = self._expect_call_args(captured)
        assert "180" in call_args

    def test_opus_model_value_passed_correctly(self, tmp_path):
        story = _make_story(id="7-6-download", yaml_status="ready-for-dev",
                             file_path=tmp_path / "story.md")
        captured = self._call_run("dev-story", story, Model.OPUS, tmp_path)
        call_args = self._expect_call_args(captured)
        assert Model.OPUS.value in call_args

    def test_no_exception_on_subprocess_failure(self, tmp_path):
        story = _make_story(file_path=tmp_path / "story.md")
        state = _make_state(tmp_path, story)
        with patch("shutil.which", side_effect=self._fake_which), \
             patch("bmad_tui.agent_runner._run_and_cleanup"), \
             patch("subprocess.run", return_value=MagicMock(stdout="", returncode=1)):
            result = run_workflow("dev-story", state, Model.SONNET, story=story)
        assert result is None

    def test_workflow_without_story_does_not_crash(self, tmp_path):
        state = _make_state(tmp_path, story=None)
        with patch("shutil.which", side_effect=self._fake_which), \
             patch("bmad_tui.agent_runner._run_and_cleanup"), \
             patch("subprocess.run", return_value=MagicMock(stdout="", returncode=0)):
            run_workflow("sprint-planning", state, Model.SONNET, story=None)

    def test_resume_passes_session_id_in_cmd(self, tmp_path):
        """When session_id is provided, expect script receives it as arg 5."""
        story = _make_story(file_path=tmp_path / "story.md")
        state = _make_state(tmp_path, story)
        uid = "99d8f74d-572d-4464-bef1-d658ec2ff8c3"
        captured: list[list] = []
        def fake_cleanup(cmd, cli_tool="copilot"):
            captured.append(list(cmd))
        with patch("shutil.which", side_effect=self._fake_which), \
             patch("bmad_tui.agent_runner._run_and_cleanup", side_effect=fake_cleanup), \
             patch("subprocess.run", return_value=MagicMock(stdout="", returncode=0)):
            run_workflow("dev-story", state, Model.SONNET, story=story, session_id=uid)
        call_args = self._expect_call_args(captured)
        assert uid in call_args

    def test_resume_passes_empty_prompt(self, tmp_path):
        """When session_id is provided, the prompt arg passed to expect is empty."""
        story = _make_story(file_path=tmp_path / "story.md")
        state = _make_state(tmp_path, story)
        uid = "99d8f74d-572d-4464-bef1-d658ec2ff8c3"
        captured: list[list] = []
        def fake_cleanup(cmd, cli_tool="copilot"):
            captured.append(list(cmd))
        with patch("shutil.which", side_effect=self._fake_which), \
             patch("bmad_tui.agent_runner._run_and_cleanup", side_effect=fake_cleanup), \
             patch("subprocess.run", return_value=MagicMock(stdout="", returncode=0)):
            run_workflow("dev-story", state, Model.SONNET, story=story, session_id=uid)
        call_args = self._expect_call_args(captured)
        # arg order: expect -f script -- model agent prompt repo_root idle session_id log
        prompt_idx = call_args.index("--") + 3  # model=+1, agent=+2, prompt=+3
        assert call_args[prompt_idx] == ""


class TestExtractSessionId:
    def test_extracts_uuid_from_resume_line(self, tmp_path):
        log = tmp_path / "session.log"
        uid = "99d8f74d-572d-4464-bef1-d658ec2ff8c3"
        log.write_text(f"some output\nResume this session with copilot --resume={uid}\n")
        assert _extract_session_id(log) == uid

    def test_returns_last_uuid_when_multiple(self, tmp_path):
        log = tmp_path / "session.log"
        uid1 = "aaaaaaaa-0000-0000-0000-000000000001"
        uid2 = "bbbbbbbb-0000-0000-0000-000000000002"
        log.write_text(f"--resume={uid1}\n--resume={uid2}\n")
        assert _extract_session_id(log) == uid2

    def test_returns_empty_when_no_match(self, tmp_path):
        log = tmp_path / "session.log"
        log.write_text("no session id here\n")
        assert _extract_session_id(log) == ""

    def test_returns_empty_when_file_missing(self, tmp_path):
        assert _extract_session_id(tmp_path / "nonexistent.log") == ""


class TestExtractSessionInfo:
    _SAMPLE = (
        "Total usage est:        0 Premium requests\r\n"
        "API time spent:         3s\r\n"
        "Total session time:     3h 53m 28s\r\n"
        "Total code changes:     +86 -8\r\n"
        "Resume this session with copilot --resume=99d8f74d-572d-4464-bef1-d658ec2ff8c3\r\n"
    )

    def test_extracts_all_fields(self, tmp_path):
        log = tmp_path / "session.log"
        log.write_text(self._SAMPLE)
        info = _extract_session_info(log)
        assert info["session_id"] == "99d8f74d-572d-4464-bef1-d658ec2ff8c3"
        assert info["usage_est"] == "0 Premium requests"
        assert info["api_time"] == "3s"
        assert info["session_time"] == "3h 53m 28s"
        assert info["code_changes"] == "+86 -8"

    def test_strips_ansi_codes(self, tmp_path):
        log = tmp_path / "session.log"
        log.write_bytes(
            b"Total session time:\x1b[32m     3h 0m 0s\x1b[0m\r\n"
        )
        info = _extract_session_info(log)
        assert info["session_time"] == "3h 0m 0s"

    def test_partial_stats_ok(self, tmp_path):
        log = tmp_path / "session.log"
        log.write_text("Total session time:     1h 2m 3s\n")
        info = _extract_session_info(log)
        assert info["session_time"] == "1h 2m 3s"
        assert info["code_changes"] == ""

    def test_missing_file_returns_empty_dict(self, tmp_path):
        info = _extract_session_info(tmp_path / "missing.log")
        assert info["session_id"] == ""
        assert info["session_time"] == ""


class TestFindLatestSessionId:
    def test_finds_newest_dir_after_timestamp(self, tmp_path):
        import time
        (tmp_path / "old-session").mkdir()
        time.sleep(0.02)
        before_ts = time.time()
        time.sleep(0.02)
        uid = "99d8f74d-572d-4464-bef1-d658ec2ff8c3"
        (tmp_path / uid).mkdir()
        assert _find_latest_session_id(before_ts, _sessions_dir=tmp_path) == uid

    def test_ignores_dirs_older_than_timestamp(self, tmp_path):
        import time
        (tmp_path / "old-session").mkdir()
        time.sleep(0.02)
        before_ts = time.time()
        assert _find_latest_session_id(before_ts, _sessions_dir=tmp_path) == ""

    def test_returns_most_recent_of_multiple_new_dirs(self, tmp_path):
        import time
        before_ts = time.time() - 1  # everything is "new"
        uid1 = "aaaaaaaa-0000-0000-0000-000000000001"
        uid2 = "bbbbbbbb-0000-0000-0000-000000000002"
        (tmp_path / uid1).mkdir()
        time.sleep(0.02)
        (tmp_path / uid2).mkdir()
        result = _find_latest_session_id(before_ts, _sessions_dir=tmp_path)
        assert result == uid2

    def test_returns_empty_when_sessions_dir_missing(self, tmp_path):
        import time
        result = _find_latest_session_id(time.time(), _sessions_dir=tmp_path / "nonexistent")
        assert result == ""

    def test_ignores_files_only_dirs(self, tmp_path):
        import time
        before_ts = time.time() - 1
        (tmp_path / "somefile.txt").write_text("x")
        result = _find_latest_session_id(before_ts, _sessions_dir=tmp_path)
        assert result == ""


class TestRunWorkflowSessionIdPriority:
    """run_workflow must prefer the log-extracted session ID over the filesystem scan.

    This prevents cross-project contamination where a concurrent Copilot session
    in a different project directory is newest by mtime and gets stored as the
    session ID for a completely unrelated run.
    """

    def _run_with_session_sources(
        self,
        tmp_path: Path,
        log_session_id: str,
        fs_session_id: str,
        resume_session_id: str = "",
    ) -> str | None:
        """Run workflow, injecting controlled session ID sources. Returns stored session_id."""
        from unittest.mock import patch, MagicMock
        story = _make_story(file_path=tmp_path / "story.md")
        state = _make_state(tmp_path, story)

        # Write a fake log that contains (or doesn't) a --resume line
        log_content = (
            f"Total session time:     1m 0s\nTotal code changes:     +5 -0\n"
            f"Resume this session with copilot --resume={log_session_id}\n"
            if log_session_id else
            "Total session time:     1m 0s\nTotal code changes:     +5 -0\n"
        )

        import tempfile, os
        fd, real_log = tempfile.mkstemp(suffix=".log")
        os.close(fd)
        Path(real_log).write_text(log_content)

        result_entry: list = []

        def fake_cleanup(cmd, cli_tool="copilot"):
            Path(real_log).write_text(log_content)  # ensure log is present after run

        def fake_mkstemp(suffix, prefix):
            return (os.open(real_log, os.O_RDWR), real_log)

        with patch("shutil.which", return_value="/usr/bin/x"), \
             patch("bmad_tui.agent_runner._run_and_cleanup", side_effect=fake_cleanup), \
             patch("bmad_tui.agent_runner._find_latest_session_id", return_value=fs_session_id), \
             patch("tempfile.mkstemp", side_effect=fake_mkstemp), \
             patch("subprocess.run", return_value=MagicMock(stdout="main\n", returncode=0)), \
             patch("bmad_tui.agent_runner.is_trivial_entry", return_value=False):
            entry = run_workflow(
                "dev-story", state, Model.SONNET,
                story=story, session_id=resume_session_id,
            )
        try:
            Path(real_log).unlink()
        except Exception:
            pass
        return entry.session_id if entry else None

    def test_log_extracted_id_beats_filesystem_id(self, tmp_path):
        """When the log has a valid UUID, it wins over the mtime-based filesystem scan."""
        log_id = "aaaaaaaa-0000-0000-0000-000000000001"
        fs_id  = "bbbbbbbb-0000-0000-0000-000000000002"  # from a concurrent Aurora session
        result = self._run_with_session_sources(tmp_path, log_id, fs_id)
        assert result == log_id

    def test_filesystem_id_used_when_log_has_no_session(self, tmp_path):
        """Falls back to filesystem scan when log parsing yields nothing."""
        fs_id = "cccccccc-0000-0000-0000-000000000003"
        result = self._run_with_session_sources(tmp_path, "", fs_id)
        assert result == fs_id

    def test_resume_id_beats_everything(self, tmp_path):
        """An explicit resume session_id always takes priority."""
        resume_id = "dddddddd-0000-0000-0000-000000000004"
        log_id    = "aaaaaaaa-0000-0000-0000-000000000001"
        fs_id     = "bbbbbbbb-0000-0000-0000-000000000002"
        result = self._run_with_session_sources(tmp_path, log_id, fs_id, resume_id)
        assert result == resume_id
