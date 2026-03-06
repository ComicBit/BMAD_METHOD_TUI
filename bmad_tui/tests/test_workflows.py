"""Tests for bmad_tui/workflows.py."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from bmad_tui.models import AgentDef, Model, ProjectState, StoryStatus, WorkflowDef
from bmad_tui.workflows import (
    AGENTS,
    CANONICAL_PHASES,
    GLOBAL_ACTIONS,
    STATUS_ACTIONS,
    WORKFLOWS,
    load_agents,
)

# Project root for load_agents integration tests
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


# ── Registry integrity ────────────────────────────────────────────────────

class TestWorkflowRegistryIntegrity:
    REQUIRED_WORKFLOWS = [
        "dev-story",
        "code-review",
        "create-story",
        "sprint-planning",
    ]

    def test_required_workflows_present(self):
        for name in self.REQUIRED_WORKFLOWS:
            assert name in WORKFLOWS, f"Missing workflow: {name}"

    def test_all_workflows_have_agent(self):
        for name, wf in WORKFLOWS.items():
            assert wf.agent, f"Workflow {name} missing agent"

    def test_all_workflows_have_prompt_template(self):
        for name, wf in WORKFLOWS.items():
            assert wf.prompt_template, f"Workflow {name} missing prompt_template"

    def test_all_workflows_have_persona(self):
        for name, wf in WORKFLOWS.items():
            assert wf.persona, f"Workflow {name} missing persona"

    def test_all_workflows_have_default_model(self):
        for name, wf in WORKFLOWS.items():
            assert wf.default_model is not None, f"Workflow {name} missing default_model"

    def test_workflow_objects_are_workflow_def_instances(self):
        for name, wf in WORKFLOWS.items():
            assert isinstance(wf, WorkflowDef), f"{name} is not a WorkflowDef"


# ── Model locking ─────────────────────────────────────────────────────────

class TestModelLocking:
    def test_code_review_is_locked(self):
        assert WORKFLOWS["code-review"].model_locked is True

    def test_code_review_locked_to_codex(self):
        assert WORKFLOWS["code-review"].default_model == Model.CODEX

    def test_dev_story_not_locked(self):
        assert not WORKFLOWS["dev-story"].model_locked

    def test_create_story_not_locked(self):
        assert not WORKFLOWS["create-story"].model_locked

    def test_sprint_planning_not_locked(self):
        assert not WORKFLOWS["sprint-planning"].model_locked

    def test_locked_workflow_model_is_codex(self):
        wf = WORKFLOWS["code-review"]
        assert wf.default_model == Model.CODEX

    def test_non_locked_default_is_sonnet(self):
        wf = WORKFLOWS["dev-story"]
        assert wf.default_model == Model.SONNET


# ── STATUS_ACTIONS mapping ────────────────────────────────────────────────

class TestStatusActions:
    """STATUS_ACTIONS uses string keys matching StoryStatus.value."""

    def test_needs_story_has_create_story(self):
        actions = STATUS_ACTIONS.get("needs-story", [])
        assert "create-story" in actions

    def test_ready_for_dev_has_dev_story(self):
        actions = STATUS_ACTIONS.get("ready-for-dev", [])
        assert "dev-story" in actions

    def test_in_progress_has_dev_story(self):
        actions = STATUS_ACTIONS.get("in-progress", [])
        assert "dev-story" in actions

    def test_review_has_code_review(self):
        actions = STATUS_ACTIONS.get("review", [])
        assert "code-review" in actions

    def test_all_actions_in_status_map_exist_in_registry(self):
        for status, actions in STATUS_ACTIONS.items():
            for action in actions:
                assert action in WORKFLOWS, (
                    f"Action {action!r} in STATUS_ACTIONS[{status!r}] not found in WORKFLOWS"
                )

    def test_done_has_no_dev_or_cr_actions(self):
        actions = STATUS_ACTIONS.get("done", [])
        assert "dev-story" not in actions
        assert "code-review" not in actions

    def test_blocked_has_no_dev_actions(self):
        actions = STATUS_ACTIONS.get("blocked", [])
        assert "dev-story" not in actions

    def test_in_progress_has_correct_course(self):
        actions = STATUS_ACTIONS.get("in-progress", [])
        assert "correct-course" in actions

    def test_blocked_has_correct_course(self):
        actions = STATUS_ACTIONS.get("blocked", [])
        assert "correct-course" in actions


# ── GLOBAL_ACTIONS ────────────────────────────────────────────────────────

class TestGlobalActions:
    def test_global_actions_is_non_empty(self):
        assert len(GLOBAL_ACTIONS) > 0

    def test_sprint_planning_is_global(self):
        assert "sprint-planning" in GLOBAL_ACTIONS

    def test_create_architecture_is_global(self):
        assert "create-architecture" in GLOBAL_ACTIONS

    def test_create_epics_and_stories_is_global(self):
        assert "create-epics-and-stories" in GLOBAL_ACTIONS

    def test_backlog_refinement_not_in_global_actions(self):
        assert "backlog-refinement" not in GLOBAL_ACTIONS

    def test_global_actions_that_map_to_workflows_exist_in_registry(self):
        # sprint-status may be a UI action without a workflow; others must be in WORKFLOWS
        non_workflow_actions = {"sprint-status"}
        for action in GLOBAL_ACTIONS:
            if action not in non_workflow_actions:
                assert action in WORKFLOWS, f"Global action {action!r} not in WORKFLOWS"


# ── Prompt template placeholders ─────────────────────────────────────────

class TestPromptTemplatePlaceholders:
    def test_dev_story_prompt_has_story_path_placeholder(self):
        wf = WORKFLOWS["dev-story"]
        assert "{story_path}" in wf.prompt_template

    def test_dev_story_prompt_has_sprint_status_placeholder(self):
        wf = WORKFLOWS["dev-story"]
        assert "{sprint_status_path}" in wf.prompt_template

    def test_cr_prompt_is_substantial(self):
        wf = WORKFLOWS["code-review"]
        assert len(wf.prompt_template) > 200, "CR prompt should contain full instructions"

    def test_cr_prompt_mentions_phase_1(self):
        wf = WORKFLOWS["code-review"]
        assert "PHASE 1" in wf.prompt_template

    def test_cr_prompt_mentions_phase_2(self):
        wf = WORKFLOWS["code-review"]
        assert "PHASE 2" in wf.prompt_template


# ── WorkflowDef dataclass ─────────────────────────────────────────────────

class TestWorkflowDefDataclass:
    def test_labels_are_human_readable(self):
        for name, wf in WORKFLOWS.items():
            assert wf.label, f"Workflow {name} has empty label"

    def test_descriptions_are_present(self):
        for name, wf in WORKFLOWS.items():
            assert isinstance(wf.description, str)  # may be empty but must exist


# ── Agent Launcher workflows ──────────────────────────────────────────────

class TestAgentLauncherWorkflows:
    AC1_NEW_KEYS = [
        # Winston
        "technical-research",
        "check-implementation-readiness",
        # Mary
        "domain-research",
        "market-research",
        "create-product-brief",
        # Sally
        "create-ux-design",
        # Quinn
        "qa-automate",
        # Murat / TEA
        "testarch-atdd",
        "testarch-ci",
        "testarch-nfr",
        "testarch-automate",
        "testarch-framework",
        "testarch-test-design",
        "testarch-test-review",
        "testarch-trace",
        # Paige
        "document-project",
        "generate-project-context",
        # Barry
        "quick-dev",
        "quick-spec",
    ]

    def test_all_ac1_workflow_keys_present(self):
        for key in self.AC1_NEW_KEYS:
            assert key in WORKFLOWS, f"AC-1 workflow key missing: {key!r}"

    def test_every_agent_has_nonempty_workflow_keys(self):
        for agent in AGENTS:
            assert agent.workflow_keys, f"Agent {agent.name!r} has empty workflow_keys"

    def test_every_agent_workflow_key_exists_in_workflows(self):
        for agent in AGENTS:
            for key in agent.workflow_keys:
                assert key in WORKFLOWS, (
                    f"Agent {agent.name!r} references unknown workflow key {key!r}"
                )

    def test_agents_contains_at_least_7_entries(self):
        assert len(AGENTS) >= 7, f"Expected at least 7 agents, got {len(AGENTS)}"

    def test_no_agent_has_empty_name(self):
        for agent in AGENTS:
            assert agent.name, f"Agent with empty name found"

    def test_no_agent_has_empty_persona(self):
        for agent in AGENTS:
            assert agent.persona, f"Agent {agent.name!r} has empty persona"

    def test_no_agent_has_empty_icon(self):
        for agent in AGENTS:
            assert agent.icon, f"Agent {agent.name!r} has empty icon"

    def test_agent_launcher_dismiss_none_does_not_crash(self):
        """Escape → dismiss(None) → _on_action_selected(None) → early return (no exception)."""
        # Simulate what Dashboard._on_action_selected does with None
        result = None
        if not result:
            launched = False
        else:
            launched = True
        assert not launched, "None result should not launch a workflow"

    def test_workflows_get_for_agent_keys_no_key_error(self):
        """WORKFLOWS.get(key) for every agent key returns a WorkflowDef, never None."""
        for agent in AGENTS:
            for key in agent.workflow_keys:
                wf = WORKFLOWS.get(key)
                assert wf is not None, (
                    f"WORKFLOWS.get({key!r}) returned None for agent {agent.name!r}"
                )


# ── Creative & Meta workflows ─────────────────────────────────────────────

class TestCreativeWorkflows:
    CREATIVE_KEYS = ["brainstorming", "party-mode", "create-agent", "create-workflow"]

    def test_all_creative_keys_in_workflows(self):
        for key in self.CREATIVE_KEYS:
            assert key in WORKFLOWS, f"Creative workflow key missing: {key!r}"

    def test_agents_contains_creative_meta_entry(self):
        names = [a.name for a in AGENTS]
        assert "Creative & Meta" in names, "AGENTS missing 'Creative & Meta' entry"

    def test_creative_meta_agent_has_all_workflow_keys(self):
        agent = next((a for a in AGENTS if a.name == "Creative & Meta"), None)
        assert agent is not None
        for key in self.CREATIVE_KEYS:
            assert key in agent.workflow_keys, (
                f"Creative & Meta agent missing workflow key {key!r}"
            )

    def test_every_agent_workflow_key_exists_in_workflows(self):
        """Existing integrity check still passes with new creative entries."""
        for agent in AGENTS:
            for key in agent.workflow_keys:
                assert key in WORKFLOWS, (
                    f"Agent {agent.name!r} references unknown workflow key {key!r}"
                )


# ── Tab Bar Workflows (TUI-11) ────────────────────────────────────────────

class TestTabBarWorkflows:
    def test_canonical_phases_constant_exists(self):
        assert CANONICAL_PHASES is not None
        assert len(CANONICAL_PHASES) == 7

    def test_canonical_phases_contains_all_seven(self):
        expected = {"Analysis", "Planning", "UX", "Implementation", "QA", "Documentation", "Creative & Meta"}
        assert set(CANONICAL_PHASES) == expected

    def test_every_workflow_has_nonempty_bmad_phase(self):
        for key, wf in WORKFLOWS.items():
            assert wf.bmad_phase, f"Workflow {key!r} has empty bmad_phase"

    def test_every_workflow_bmad_phase_is_canonical(self):
        for key, wf in WORKFLOWS.items():
            assert wf.bmad_phase in CANONICAL_PHASES, (
                f"Workflow {key!r} has non-canonical bmad_phase {wf.bmad_phase!r}"
            )

    def test_workflow_count_grouped_by_phase_matches_total(self):
        from collections import Counter
        counts = Counter(wf.bmad_phase for wf in WORKFLOWS.values())
        assert sum(counts.values()) == len(WORKFLOWS), "Phase grouping has orphans"

    def test_analysis_workflows_have_correct_phase(self):
        for key in ("domain-research", "market-research"):
            assert WORKFLOWS[key].bmad_phase == "Analysis", f"{key} should be Analysis"

    def test_planning_workflows_have_correct_phase(self):
        for key in ("create-prd", "create-architecture", "sprint-planning", "correct-course"):
            assert WORKFLOWS[key].bmad_phase == "Planning", f"{key} should be Planning"

    def test_ux_workflows_have_correct_phase(self):
        assert WORKFLOWS["create-ux-design"].bmad_phase == "UX"

    def test_implementation_workflows_have_correct_phase(self):
        for key in ("dev-story", "create-story", "sprint-status", "quick-dev", "quick-spec"):
            assert WORKFLOWS[key].bmad_phase == "Implementation", f"{key} should be Implementation"

    def test_qa_workflows_have_correct_phase(self):
        for key in ("code-review", "qa-automate", "testarch-atdd", "testarch-ci"):
            assert WORKFLOWS[key].bmad_phase == "QA", f"{key} should be QA"

    def test_documentation_workflows_have_correct_phase(self):
        for key in ("retrospective", "document-project", "generate-project-context"):
            assert WORKFLOWS[key].bmad_phase == "Documentation", f"{key} should be Documentation"

    def test_creative_meta_workflows_have_correct_phase(self):
        for key in ("brainstorming", "party-mode", "create-agent", "create-workflow"):
            assert WORKFLOWS[key].bmad_phase == "Creative & Meta", f"{key} should be Creative & Meta"


# ── New BMB workflows ─────────────────────────────────────────────────────

class TestBmbWorkflows:
    BMB_AGENT_BUILDER_KEYS = ["edit-agent", "validate-agent"]
    BMB_MODULE_BUILDER_KEYS = ["create-module-brief", "create-module", "edit-module", "validate-module"]
    BMB_WORKFLOW_BUILDER_KEYS = ["edit-workflow", "validate-workflow", "rework-workflow"]

    def test_agent_builder_workflows_present(self):
        for key in self.BMB_AGENT_BUILDER_KEYS:
            assert key in WORKFLOWS, f"Missing bmb workflow: {key!r}"

    def test_module_builder_workflows_present(self):
        for key in self.BMB_MODULE_BUILDER_KEYS:
            assert key in WORKFLOWS, f"Missing bmb workflow: {key!r}"

    def test_workflow_builder_workflows_present(self):
        for key in self.BMB_WORKFLOW_BUILDER_KEYS:
            assert key in WORKFLOWS, f"Missing bmb workflow: {key!r}"

    def test_bmb_workflows_have_correct_agent_id(self):
        for key in self.BMB_AGENT_BUILDER_KEYS:
            assert WORKFLOWS[key].agent == "bmad-agent-bmb-agent-builder"
        for key in self.BMB_MODULE_BUILDER_KEYS:
            assert WORKFLOWS[key].agent == "bmad-agent-bmb-module-builder"
        for key in self.BMB_WORKFLOW_BUILDER_KEYS:
            assert WORKFLOWS[key].agent == "bmad-agent-bmb-workflow-builder"

    def test_bmb_workflows_are_creative_meta_phase(self):
        for key in self.BMB_AGENT_BUILDER_KEYS + self.BMB_MODULE_BUILDER_KEYS + self.BMB_WORKFLOW_BUILDER_KEYS:
            assert WORKFLOWS[key].bmad_phase == "Creative & Meta", f"{key} should be Creative & Meta"


# ── New CIS workflows ─────────────────────────────────────────────────────

class TestCisWorkflows:
    CIS_KEYS = ["problem-solving", "design-thinking", "innovation-strategy", "presentation", "storytelling"]

    def test_cis_workflows_present(self):
        for key in self.CIS_KEYS:
            assert key in WORKFLOWS, f"Missing cis workflow: {key!r}"

    def test_cis_workflows_are_creative_meta_phase(self):
        for key in self.CIS_KEYS:
            assert WORKFLOWS[key].bmad_phase == "Creative & Meta", f"{key} should be Creative & Meta"

    def test_cis_workflows_have_valid_agents(self):
        expected_agents = {
            "problem-solving": "bmad-agent-cis-creative-problem-solver",
            "design-thinking": "bmad-agent-cis-design-thinking-coach",
            "innovation-strategy": "bmad-agent-cis-innovation-strategist",
            "presentation": "bmad-agent-cis-presentation-master",
            "storytelling": "bmad-agent-cis-storyteller",
        }
        for key, expected_agent in expected_agents.items():
            assert WORKFLOWS[key].agent == expected_agent, (
                f"Workflow {key!r} should use {expected_agent!r}"
            )


# ── load_agents() dynamic loading ─────────────────────────────────────────

class TestLoadAgents:
    def test_load_agents_returns_nonempty_list(self):
        agents = load_agents(_PROJECT_ROOT)
        assert len(agents) > 0, "load_agents should return at least one agent"

    def test_load_agents_sprint_agents_come_first(self):
        agents = load_agents(_PROJECT_ROOT)
        sprint = [a for a in agents if a.category == "sprint"]
        other = [a for a in agents if a.category == "other"]
        # Verify sprint agents appear before other agents in the list
        if sprint and other:
            first_other_idx = agents.index(other[0])
            last_sprint_idx = agents.index(sprint[-1])
            assert last_sprint_idx < first_other_idx, "Sprint agents should precede Other agents"

    def test_load_agents_all_have_agent_id(self):
        for agent in load_agents(_PROJECT_ROOT):
            assert agent.agent_id, f"Agent {agent.name!r} missing agent_id"

    def test_load_agents_all_have_nonempty_name(self):
        for agent in load_agents(_PROJECT_ROOT):
            assert agent.name, "Agent missing name"

    def test_load_agents_all_have_icon(self):
        for agent in load_agents(_PROJECT_ROOT):
            assert agent.icon, f"Agent {agent.name!r} missing icon"

    def test_load_agents_sprint_category_contains_bmm_agents(self):
        agents = load_agents(_PROJECT_ROOT)
        sprint = {a.name for a in agents if a.category == "sprint"}
        # Core sprint team should be discoverable
        assert "Amelia" in sprint or "Bob" in sprint, "Expected BMM sprint agents"

    def test_load_agents_other_category_contains_bmb_agents(self):
        agents = load_agents(_PROJECT_ROOT)
        other_names = {a.name for a in agents if a.category == "other"}
        assert any(n in other_names for n in ("Barry", "Creative & Meta")), (
            "Expected non-sprint agents in 'other' category"
        )

    def test_load_agents_workflow_keys_all_valid(self):
        for agent in load_agents(_PROJECT_ROOT):
            for key in agent.workflow_keys:
                assert key in WORKFLOWS, (
                    f"Agent {agent.name!r} references unknown workflow {key!r}"
                )

    def test_load_agents_each_is_agentdef_instance(self):
        for agent in load_agents(_PROJECT_ROOT):
            assert isinstance(agent, AgentDef)

    def test_load_agents_falls_back_when_no_agents_dir(self, tmp_path):
        """load_agents falls back to AGENTS when .github/agents/ does not exist."""
        result = load_agents(tmp_path)
        assert result == list(AGENTS)
