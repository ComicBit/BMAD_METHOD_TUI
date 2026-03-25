"""Registry of all BMAD workflows available in the TUI.

Each WorkflowDef captures the Copilot agent ID, persona, default model,
and a prompt template. Templates support {story_id}, {story_path}, and
{sprint_status_path} substitutions.
"""

from __future__ import annotations

import csv as _csv
from pathlib import Path

from .models import AgentDef, Model, WorkflowDef

CANONICAL_PHASES: tuple[str, ...] = (
    "Analysis",
    "Planning",
    "UX",
    "Implementation",
    "QA",
    "Documentation",
    "Creative & Meta",
)

# ---------------------------------------------------------------------------
# CR Loop prompt — kept identical to cr-loop.sh to maintain audit consistency
# ---------------------------------------------------------------------------
_CR_PROMPT = (
    "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. PROCEED IMMEDIATELY TO PHASE 1 "
    "WITHOUT ANY PROMPTS OR QUESTIONS. Please always ignore unrelated changes to our task "
    "and leave them untouched.\n"
    "COMPREHENSIVE CODE REVIEW — two-phase: AUDIT then FIX ALL.\n\n"
    "Read the current branch name with: git rev-parse --abbrev-ref HEAD\n"
    "Read the findings file path: FINDINGS=artifacts/logs/cr-loop/findings_{story_slug}.md\n\n"
    "════════════════════════════════════════════════════\n"
    "PHASE 1 — FULL AUDIT  (read-only: NO code changes, NO commits)\n"
    "════════════════════════════════════════════════════\n\n"
    "1. Read the story file for this branch from _bmad-output/implementation-artifacts/\n"
    "2. Run ALL four gates: xctask_auroracore_test, xctask_test_focused, xctask_build_macos, xctask_build_ios_sim\n"
    "3. Read the full git diff vs the default branch (a-fresh-start-for-our-heroes)\n"
    "4. Audit for issue classes A–I (fail-open, missing wiring, boundary violations, "
    "localization, missing failure tests, nondeterministic state, missing wiring tests, "
    "story AC gaps, file list accuracy)\n"
    "5. APPEND findings to FINDINGS file. If zero findings and all gates green: write CLEAN and STOP.\n\n"
    "════════════════════════════════════════════════════\n"
    "PHASE 2 — FIX ALL  (only if findings exist)\n"
    "════════════════════════════════════════════════════\n\n"
    "6. Fix ALL open findings CRITICAL→HIGH→MEDIUM→LOW.\n"
    "7. Re-run all four gates and confirm green.\n"
    "8. Mark each finding RESOLVED.\n"
    "9. Update story Dev Agent Record.\n"
    "10. ONE git commit: 'fix({story_id}): resolve CR findings — N items'\n\n"
    "CRITICAL: ONE commit only after all fixes. Do NOT prompt or show menu."
)

# ---------------------------------------------------------------------------
# Workflow registry
# ---------------------------------------------------------------------------
WORKFLOWS: dict[str, WorkflowDef] = {
    # ── Implementation ──────────────────────────────────────────────────────
    "dev-story": WorkflowDef(
        label="Dev Story",
        agent="bmad-agent-bmm-dev",
        persona="Amelia (Dev) 💻",
        default_model=Model.SONNET,
        description="Implement all tasks/subtasks for the story, write tests, validate ACs.",
        bmad_phase="Implementation",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Execute the dev-story workflow.\n"
            "Story file: {story_path}\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "code-review": WorkflowDef(
        label="CR Loop",
        agent="bmad-agent-bmm-dev",
        persona="CR Loop 🤖",
        default_model=Model.CODEX,
        model_locked=True,
        description="Two-phase audit+fix code review. Always runs on gpt-5.3-codex.",
        bmad_phase="QA",
        prompt_template=_CR_PROMPT,
    ),
    "create-story": WorkflowDef(
        label="Create Story",
        agent="bmad-agent-bmm-sm",
        persona="Bob (SM) 🏃",
        default_model=Model.SONNET,
        description="Generate the story .md file from the epic, PRD, and architecture.",
        bmad_phase="Implementation",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the create-story workflow.\n"
            "Target story ID: {story_id}\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "validate-story": WorkflowDef(
        label="Validate Story",
        agent="bmad-agent-bmm-sm",
        persona="Bob (SM) 🏃",
        default_model=Model.SONNET,
        description="Review story file for completeness, ACs, and alignment before dev.",
        bmad_phase="Planning",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the create-story workflow in Validate Mode.\n"
            "Target story ID: {story_id}\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "correct-course": WorkflowDef(
        label="Correct Course",
        agent="bmad-agent-bmm-sm",
        persona="Bob (SM) 🏃",
        default_model=Model.SONNET,
        description="Mid-sprint pivot — reassess approach, update story, realign with PRD.",
        bmad_phase="Planning",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the correct-course workflow.\n"
            "Story file: {story_path}\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    # ── Planning ────────────────────────────────────────────────────────────
    "sprint-planning": WorkflowDef(
        label="Sprint Planning",
        agent="bmad-agent-bmm-sm",
        persona="Bob (SM) 🏃",
        default_model=Model.SONNET,
        description="Regenerate / update sprint-status.yaml from epic files.",
        bmad_phase="Planning",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the sprint-planning workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "sprint-status": WorkflowDef(
        label="Sprint Status",
        agent="bmad-agent-bmm-sm",
        persona="Bob (SM) 🏃",
        default_model=Model.SONNET,
        description="Summarise current sprint, surface risks, route to next workflow.",
        bmad_phase="Implementation",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the sprint-status workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    # ── New project bootstrap ────────────────────────────────────────────────
    "create-prd": WorkflowDef(
        label="Create PRD",
        agent="bmad-agent-bmm-pm",
        persona="John (PM) 📋",
        default_model=Model.SONNET,
        description="Collaborative PRD creation through structured discovery.",
        bmad_phase="Planning",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the create-prd workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "create-architecture": WorkflowDef(
        label="Create Architecture",
        agent="bmad-agent-bmm-architect",
        persona="Winston (Architect) 🏗️",
        default_model=Model.SONNET,
        description="Architectural decisions — patterns, boundaries, tech stack. [re-run]",
        bmad_phase="Planning",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the create-architecture workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "create-epics-and-stories": WorkflowDef(
        label="Create Epics & Stories",
        agent="bmad-agent-bmm-sm",
        persona="Bob (SM) 🏃",
        default_model=Model.SONNET,
        description="Transform PRD + architecture into implementation-ready epics. [re-run]",
        bmad_phase="Planning",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the create-epics-and-stories workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "retrospective": WorkflowDef(
        label="Retrospective",
        agent="bmad-agent-bmm-sm",
        persona="Bob (SM) 🏃",
        default_model=Model.SONNET,
        description="Run epic retrospective — capture learnings, update process docs.",
        bmad_phase="Documentation",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the sprint retrospective workflow for Epic {epic_id}.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    # ── Architect / Winston ─────────────────────────────────────────────────
    "technical-research": WorkflowDef(
        label="Technical Research",
        agent="bmad-agent-bmm-architect",
        persona="Winston (Architect) 🏗️",
        default_model=Model.SONNET,
        description="Deep-dive technical research on a specific technology or architectural pattern.",
        bmad_phase="Planning",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the technical-research workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "check-implementation-readiness": WorkflowDef(
        label="Check Implementation Readiness",
        agent="bmad-agent-bmm-architect",
        persona="Winston (Architect) 🏗️",
        default_model=Model.SONNET,
        description="Validate that stories are ready for implementation from an architectural standpoint.",
        bmad_phase="Planning",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the check-implementation-readiness workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    # ── Analyst / Mary ──────────────────────────────────────────────────────
    "domain-research": WorkflowDef(
        label="Domain Research",
        agent="bmad-agent-bmm-analyst",
        persona="Mary (Analyst) 📊",
        default_model=Model.SONNET,
        description="Research the problem domain, user needs, and market context.",
        bmad_phase="Analysis",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the domain-research workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "market-research": WorkflowDef(
        label="Market Research",
        agent="bmad-agent-bmm-analyst",
        persona="Mary (Analyst) 📊",
        default_model=Model.SONNET,
        description="Competitive analysis and market landscape research.",
        bmad_phase="Analysis",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the market-research workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "create-product-brief": WorkflowDef(
        label="Create Product Brief",
        agent="bmad-agent-bmm-analyst",
        persona="Mary (Analyst) 📊",
        default_model=Model.SONNET,
        description="Synthesise research into a concise product brief.",
        bmad_phase="Planning",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the create-product-brief workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    # ── UX / Sally ──────────────────────────────────────────────────────────
    "create-ux-design": WorkflowDef(
        label="Create UX Design",
        agent="bmad-agent-bmm-ux-designer",
        persona="Sally (UX) 🎨",
        default_model=Model.SONNET,
        description="Design user flows, interaction patterns, and UI specifications.",
        bmad_phase="UX",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the create-ux-design workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    # ── QA / Quinn ──────────────────────────────────────────────────────────
    "qa-automate": WorkflowDef(
        label="QA Automate",
        agent="bmad-agent-bmm-qa",
        persona="Quinn (QA) 🧪",
        default_model=Model.SONNET,
        description="Generate automated test suites and coverage analysis.",
        bmad_phase="QA",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the qa-automate workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    # ── TEA / Murat ─────────────────────────────────────────────────────────
    "testarch-atdd": WorkflowDef(
        label="TestArch: ATDD",
        agent="bmad-agent-tea",
        persona="Murat (TEA) 🧪",
        default_model=Model.SONNET,
        description="Acceptance Test-Driven Development — define acceptance tests first.",
        bmad_phase="QA",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the testarch-atdd workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "testarch-ci": WorkflowDef(
        label="TestArch: CI",
        agent="bmad-agent-tea",
        persona="Murat (TEA) 🧪",
        default_model=Model.SONNET,
        description="Design and validate CI pipeline test gates.",
        bmad_phase="QA",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the testarch-ci workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "testarch-nfr": WorkflowDef(
        label="TestArch: NFR",
        agent="bmad-agent-tea",
        persona="Murat (TEA) 🧪",
        default_model=Model.SONNET,
        description="Non-functional requirements testing strategy.",
        bmad_phase="QA",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the testarch-nfr workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "testarch-automate": WorkflowDef(
        label="TestArch: Automate",
        agent="bmad-agent-tea",
        persona="Murat (TEA) 🧪",
        default_model=Model.SONNET,
        description="Test automation strategy and tooling selection.",
        bmad_phase="QA",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the testarch-automate workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "testarch-framework": WorkflowDef(
        label="TestArch: Framework",
        agent="bmad-agent-tea",
        persona="Murat (TEA) 🧪",
        default_model=Model.SONNET,
        description="Design the test framework architecture.",
        bmad_phase="QA",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the testarch-framework workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "testarch-test-design": WorkflowDef(
        label="TestArch: Test Design",
        agent="bmad-agent-tea",
        persona="Murat (TEA) 🧪",
        default_model=Model.SONNET,
        description="Design comprehensive test cases for a story or feature.",
        bmad_phase="QA",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the testarch-test-design workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "testarch-test-review": WorkflowDef(
        label="TestArch: Test Review",
        agent="bmad-agent-tea",
        persona="Murat (TEA) 🧪",
        default_model=Model.SONNET,
        description="Review existing tests for coverage gaps and quality issues.",
        bmad_phase="QA",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the testarch-test-review workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "testarch-trace": WorkflowDef(
        label="TestArch: Trace",
        agent="bmad-agent-tea",
        persona="Murat (TEA) 🧪",
        default_model=Model.SONNET,
        description="Traceability matrix — link requirements to tests.",
        bmad_phase="QA",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the testarch-trace workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    # ── Tech Writer / Paige ─────────────────────────────────────────────────
    "document-project": WorkflowDef(
        label="Document Project",
        agent="bmad-agent-bmm-tech-writer",
        persona="Paige (Tech Writer) 📚",
        default_model=Model.SONNET,
        description="Generate comprehensive project documentation.",
        bmad_phase="Documentation",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the document-project workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "generate-project-context": WorkflowDef(
        label="Generate Project Context",
        agent="bmad-agent-bmm-tech-writer",
        persona="Paige (Tech Writer) 📚",
        default_model=Model.SONNET,
        description="Generate a project context document for onboarding and reference.",
        bmad_phase="Documentation",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the generate-project-context workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    # ── Quick Flow / Barry ──────────────────────────────────────────────────
    "quick-dev": WorkflowDef(
        label="Quick Dev",
        agent="bmad-agent-bmm-quick-flow-solo-dev",
        persona="Barry (Quick Flow) 🚀",
        default_model=Model.SONNET,
        description="Rapid implementation with minimum ceremony.",
        bmad_phase="Implementation",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the quick-dev workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "quick-spec": WorkflowDef(
        label="Quick Spec",
        agent="bmad-agent-bmm-quick-flow-solo-dev",
        persona="Barry (Quick Flow) 🚀",
        default_model=Model.SONNET,
        description="Rapid spec creation — lean, actionable, low ceremony.",
        bmad_phase="Implementation",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the quick-spec workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    # ── Creative & Meta ─────────────────────────────────────────────────────
    "brainstorming": WorkflowDef(
        label="Brainstorming",
        agent="bmad-agent-cis-brainstorming-coach",
        persona="Carson (Brainstorming) 🧠",
        default_model=Model.SONNET,
        description="Interactive brainstorming session using diverse creative techniques.",
        bmad_phase="Creative & Meta",
        prompt_template=(
            "Load and follow the brainstorming workflow at "
            "{project-root}/_bmad/core/workflows/brainstorming/workflow.md. "
            "Begin the session immediately — do not show any menus."
        ),
    ),
    "party-mode": WorkflowDef(
        label="Party Mode",
        agent="bmad-agent-bmad-master",
        persona="BMad Master 🧠",
        default_model=Model.SONNET,
        description="Multi-agent party mode — all BMAD agents collaborate simultaneously.",
        bmad_phase="Creative & Meta",
        prompt_template=(
            "Load and follow the party-mode workflow at "
            "{project-root}/_bmad/core/workflows/party-mode/workflow.md. "
            "Begin immediately — do not show any menus."
        ),
    ),
    "create-agent": WorkflowDef(
        label="Create Agent",
        agent="bmad-agent-bmad-master",
        persona="BMad Master 🧠",
        default_model=Model.SONNET,
        description="Create a new BMAD agent definition file.",
        bmad_phase="Creative & Meta",
        prompt_template=(
            "You are BMad Master. Create a new BMAD agent definition file in "
            "{project-root}/_bmad/bmm/agents/. "
            "Follow the conventions of existing agents in that directory. "
            "Ask me for the agent name, persona, title, and capabilities, "
            "then generate the agent .md file."
        ),
    ),
    "create-workflow": WorkflowDef(
        label="Create Workflow",
        agent="bmad-agent-bmad-master",
        persona="BMad Master 🧠",
        default_model=Model.OPUS,
        description="Create a new BMAD workflow YAML definition.",
        bmad_phase="Creative & Meta",
        prompt_template=(
            "You are BMad Master. Create a new BMAD workflow YAML in "
            "{project-root}/_bmad/bmm/workflows/. "
            "Ask me for the workflow name, phase, and steps, "
            "then generate the workflow file following existing conventions in "
            "{project-root}/_bmad/bmm/workflows/."
        ),
    ),
    # ── BMB — Agent Builder (Bond) ──────────────────────────────────────────
    "edit-agent": WorkflowDef(
        label="Edit Agent",
        agent="bmad-agent-bmb-agent-builder",
        persona="Bond (Agent Builder) 🤖",
        default_model=Model.SONNET,
        description="Edit an existing BMAD agent definition file.",
        bmad_phase="Creative & Meta",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the edit-agent workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "validate-agent": WorkflowDef(
        label="Validate Agent",
        agent="bmad-agent-bmb-agent-builder",
        persona="Bond (Agent Builder) 🤖",
        default_model=Model.SONNET,
        description="Validate an existing BMAD agent against best practices.",
        bmad_phase="Creative & Meta",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the validate-agent workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    # ── BMB — Module Builder (Morgan) ───────────────────────────────────────
    "create-module-brief": WorkflowDef(
        label="Create Module Brief",
        agent="bmad-agent-bmb-module-builder",
        persona="Morgan (Module Builder) 🏗️",
        default_model=Model.SONNET,
        description="Create a product brief for a new BMAD module.",
        bmad_phase="Creative & Meta",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the create-module-brief workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "create-module": WorkflowDef(
        label="Create Module",
        agent="bmad-agent-bmb-module-builder",
        persona="Morgan (Module Builder) 🏗️",
        default_model=Model.SONNET,
        description="Create a complete BMAD module with agents, workflows, and infrastructure.",
        bmad_phase="Creative & Meta",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the create-module workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "edit-module": WorkflowDef(
        label="Edit Module",
        agent="bmad-agent-bmb-module-builder",
        persona="Morgan (Module Builder) 🏗️",
        default_model=Model.SONNET,
        description="Edit an existing BMAD module while maintaining coherence.",
        bmad_phase="Creative & Meta",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the edit-module workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "validate-module": WorkflowDef(
        label="Validate Module",
        agent="bmad-agent-bmb-module-builder",
        persona="Morgan (Module Builder) 🏗️",
        default_model=Model.SONNET,
        description="Run compliance checks on a BMAD module against best practices.",
        bmad_phase="Creative & Meta",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the validate-module workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    # ── BMB — Workflow Builder (Wendy) ──────────────────────────────────────
    "edit-workflow": WorkflowDef(
        label="Edit Workflow",
        agent="bmad-agent-bmb-workflow-builder",
        persona="Wendy (Workflow Builder) 🔄",
        default_model=Model.SONNET,
        description="Edit an existing BMAD workflow while maintaining integrity.",
        bmad_phase="Creative & Meta",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the edit-workflow workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "validate-workflow": WorkflowDef(
        label="Validate Workflow",
        agent="bmad-agent-bmb-workflow-builder",
        persona="Wendy (Workflow Builder) 🔄",
        default_model=Model.SONNET,
        description="Run validation checks on a BMAD workflow against best practices.",
        bmad_phase="Creative & Meta",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the validate-workflow workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    "rework-workflow": WorkflowDef(
        label="Rework Workflow",
        agent="bmad-agent-bmb-workflow-builder",
        persona="Wendy (Workflow Builder) 🔄",
        default_model=Model.SONNET,
        description="Rework a workflow to a V6-compliant version.",
        bmad_phase="Creative & Meta",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the rework-workflow workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    # ── CIS — Creative Problem Solver (Dr. Quinn) ───────────────────────────
    "problem-solving": WorkflowDef(
        label="Problem Solving",
        agent="bmad-agent-cis-creative-problem-solver",
        persona="Dr. Quinn (Problem Solver) 🔬",
        default_model=Model.SONNET,
        description="Apply systematic problem-solving to crack complex challenges.",
        bmad_phase="Creative & Meta",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the problem-solving workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    # ── CIS — Design Thinking Coach (Maya) ──────────────────────────────────
    "design-thinking": WorkflowDef(
        label="Design Thinking",
        agent="bmad-agent-cis-design-thinking-coach",
        persona="Maya (Design Thinking) 🎨",
        default_model=Model.SONNET,
        description="Guide human-centered design processes using empathy-driven methodologies.",
        bmad_phase="Creative & Meta",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the design-thinking workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    # ── CIS — Innovation Strategist (Victor) ────────────────────────────────
    "innovation-strategy": WorkflowDef(
        label="Innovation Strategy",
        agent="bmad-agent-cis-innovation-strategist",
        persona="Victor (Innovation) ⚡",
        default_model=Model.SONNET,
        description="Identify disruption opportunities and architect business model innovation.",
        bmad_phase="Creative & Meta",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the innovation-strategy workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    # ── CIS — Presentation Master (Caravaggio) ───────────────────────────────
    "presentation": WorkflowDef(
        label="Presentation",
        agent="bmad-agent-cis-presentation-master",
        persona="Caravaggio (Presentation) 🎨",
        default_model=Model.SONNET,
        description="Create visually stunning presentations and communication materials.",
        bmad_phase="Creative & Meta",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run a presentation design session.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
    # ── CIS — Storyteller (Sophia) ───────────────────────────────────────────
    "storytelling": WorkflowDef(
        label="Storytelling",
        agent="bmad-agent-cis-storyteller",
        persona="Sophia (Storyteller) 📖",
        default_model=Model.SONNET,
        description="Craft compelling narratives using proven story frameworks.",
        bmad_phase="Creative & Meta",
        prompt_template=(
            "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
            "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
            "Run the storytelling workflow.\n"
            "Sprint status: {sprint_status_path}"
        ),
    ),
}

# Actions available per effective status (primary first)
STATUS_ACTIONS: dict[str, list[str]] = {
    "needs-story": ["create-story", "validate-story"],
    "ready-for-dev": ["dev-story", "validate-story", "check-implementation-readiness"],
    "in-progress": ["dev-story", "correct-course"],
    "review": ["code-review"],
    "backlog": ["create-story", "validate-story"],
    "done": [],
    "blocked": ["correct-course"],
    "unknown": [],
}

# Global actions always available from the dashboard footer
GLOBAL_ACTIONS: list[str] = [
    "sprint-planning",
    "sprint-status",
    "create-story",
    "create-architecture",
    "create-epics-and-stories",
]

# Agent registry — one entry per launchable BMAD agent
AGENTS: list[AgentDef] = [
    AgentDef(
        name="Bob", persona="Bob (SM) 🏃", icon="🏃",
        workflow_keys=["create-story", "sprint-planning", "sprint-status", "retrospective",
                       "create-epics-and-stories"],
        role="Scrum Master",
        description="Sprint planning and agile ceremonies specialist. Creates stories, manages the backlog, and keeps the team moving forward.",
        agent_id="bmad-agent-bmm-sm",
    ),
    AgentDef(
        name="Amelia", persona="Amelia (Dev) 💻", icon="💻",
        workflow_keys=["dev-story", "code-review"],
        role="Developer",
        description="Story execution specialist. Writes code and tests with strict adherence to story ACs and team standards.",
        agent_id="bmad-agent-bmm-dev",
    ),
    AgentDef(
        name="Winston", persona="Winston (Architect) 🏗️", icon="🏗️",
        workflow_keys=["create-architecture", "technical-research",
                       "check-implementation-readiness"],
        role="Architect",
        description="System design specialist. Defines technical architecture, evaluates implementation readiness, and conducts technical research.",
        agent_id="bmad-agent-bmm-architect",
    ),
    AgentDef(
        name="Mary", persona="Mary (Analyst) 📊", icon="📊",
        workflow_keys=["domain-research", "market-research", "create-product-brief"],
        role="Business Analyst",
        description="Domain and market research specialist. Elicits requirements, performs competitive analysis, and creates product briefs.",
        agent_id="bmad-agent-bmm-analyst",
    ),
    AgentDef(
        name="John", persona="John (PM) 📋", icon="📋",
        workflow_keys=["create-prd", "create-epics-and-stories"],
        role="Product Manager",
        description="Product strategy specialist. Creates PRDs, defines epics and stories, and aligns stakeholders.",
        agent_id="bmad-agent-bmm-pm",
    ),
    AgentDef(
        name="Sally", persona="Sally (UX) 🎨", icon="🎨",
        workflow_keys=["create-ux-design"],
        role="UX Designer",
        description="User experience specialist. Designs interaction flows, UI patterns, and experience strategy.",
        agent_id="bmad-agent-bmm-ux-designer",
    ),
    AgentDef(
        name="Quinn", persona="Quinn (QA) 🧪", icon="🧪",
        workflow_keys=["qa-automate"],
        role="QA Engineer",
        description="Quality assurance specialist. Automates tests, covers critical paths, and ensures release quality.",
        agent_id="bmad-agent-bmm-qa",
    ),
    AgentDef(
        name="Murat", persona="Murat (TEA) 🔬", icon="🔬",
        workflow_keys=["testarch-atdd", "testarch-ci", "testarch-nfr", "testarch-automate",
                       "testarch-framework", "testarch-test-design", "testarch-test-review",
                       "testarch-trace"],
        role="Test Architect",
        description="Test architecture specialist. Designs ATDD frameworks, CI quality gates, and NFR test strategies.",
        agent_id="bmad-agent-tea-tea",
    ),
    AgentDef(
        name="Paige", persona="Paige (Tech Writer) 📚", icon="📚",
        workflow_keys=["document-project", "generate-project-context"],
        role="Technical Writer",
        description="Documentation specialist. Writes project docs, generates context files, and maintains living documentation.",
        agent_id="bmad-agent-bmm-tech-writer",
    ),
    AgentDef(
        name="Barry", persona="Barry (Quick Flow) 🚀", icon="🚀",
        workflow_keys=["quick-dev", "quick-spec"],
        role="Quick Flow Dev",
        description="Rapid delivery specialist. Creates lean specs and ships minimal-ceremony features fast.",
        category="other",
        agent_id="bmad-agent-bmm-quick-flow-solo-dev",
    ),
    AgentDef(
        name="Creative & Meta", persona="Creative & Meta 🎭", icon="🎭",
        workflow_keys=["brainstorming", "party-mode", "create-agent", "create-workflow"],
        role="Meta Agent",
        description="Creative and meta workflows. Brainstorming, party mode, and creation of new agents and workflows.",
        category="other",
        agent_id="bmad-agent-bmad-master",
    ),
]

# ---------------------------------------------------------------------------
# Sprint-first display order for load_agents()
# ---------------------------------------------------------------------------
_SPRINT_ORDER = [
    "Bob", "Amelia", "Winston", "Mary", "John",
    "Sally", "Quinn", "Murat", "Paige", "Barry",
]

# Modules whose agents belong to the "Sprint" category
_SPRINT_MODULES = {"bmm", "tea"}

# Mapping from agent file stem → manifest "name" key (handles non-standard naming)
_AGENT_ID_TO_MANIFEST_KEY: dict[str, str] = {
    "bmad-agent-bmad-master": "bmad-master",
    "bmad-agent-tea-tea": "tea",
}


def load_agents(project_root: Path) -> list[AgentDef]:
    """Dynamically load agents from BMAD installation.
    
    Discovery priority:
    1. Parse _bmad/_config/skill-manifest.csv and agent files (full dynamic discovery)
    2. Parse .github/agents/*.agent.md (legacy Aurora format)
    3. Fall back to hardcoded AGENTS list (backward compat)
    
    Args:
        project_root: Absolute path to the repository root.
    
    Returns:
        List of AgentDef objects — Sprint agents first, then Other agents.
    """
    from .agent_discovery import discover_agents, merge_agents_with_manual, merge_workflows_with_manual
    
    # Try full BMAD discovery first (skill-manifest.csv + agent files)
    discovered_agents, discovered_workflows = discover_agents(project_root)
    
    if discovered_agents:
        # Update global WORKFLOWS dict with discovered workflows
        global WORKFLOWS
        WORKFLOWS = merge_workflows_with_manual(discovered_workflows, WORKFLOWS)
        
        # Merge discovered with hardcoded (manual takes priority)
        return merge_agents_with_manual(discovered_agents, AGENTS)
    
    # Fall back to legacy .github/agents/ discovery
    return _load_agents_legacy(project_root)


def _load_agents_legacy(project_root: Path) -> list[AgentDef]:
    """Legacy: Load agents from ``.github/agents/bmad-agent-*.agent.md`` files.

    Falls back to the static ``AGENTS`` list when no agent directory is found.
    Each discovered agent is enriched with display metadata from the BMAD
    agent-manifest CSV. Workflow keys are auto-discovered by matching the agent
    CLI ID against entries in ``WORKFLOWS``.

    Args:
        project_root: Absolute path to the repository root.

    Returns:
        List of ``AgentDef`` objects — Sprint agents first (in canonical order),
        then Other agents sorted alphabetically.
    """
    agents_dir = project_root / ".github" / "agents"
    manifest_path = project_root / "_bmad" / "_config" / "agent-manifest.csv"

    if not agents_dir.exists():
        return list(AGENTS)

    # ------------------------------------------------------------------
    # 1. Build manifest index: name-key → row dict
    # ------------------------------------------------------------------
    manifest_index: dict[str, dict[str, str]] = {}
    if manifest_path.exists():
        try:
            with manifest_path.open(encoding="utf-8") as f:
                reader = _csv.DictReader(f)
                for row in reader:
                    manifest_index[row["name"]] = row
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 2. Build agent_id → workflow_keys reverse index
    # ------------------------------------------------------------------
    agent_workflow_map: dict[str, list[str]] = {}
    for wf_key, wf in WORKFLOWS.items():
        agent_workflow_map.setdefault(wf.agent, []).append(wf_key)
    # Legacy alias: "bmad-master" agent also reachable as the full agent ID
    if "bmad-master" in agent_workflow_map:
        agent_workflow_map.setdefault("bmad-agent-bmad-master", []).extend(
            agent_workflow_map["bmad-master"]
        )
    # Legacy alias: TEA workflows registered as "bmad-agent-tea" map to file "bmad-agent-tea-tea"
    if "bmad-agent-tea" in agent_workflow_map:
        agent_workflow_map.setdefault("bmad-agent-tea-tea", []).extend(
            agent_workflow_map["bmad-agent-tea"]
        )

    # ------------------------------------------------------------------
    # 3. Scan agent files
    # ------------------------------------------------------------------
    sprint_agents: list[AgentDef] = []
    other_agents: list[AgentDef] = []

    for agent_file in sorted(agents_dir.glob("bmad-agent-*.agent.md")):
        agent_id = agent_file.name.replace(".agent.md", "")

        # Derive module and manifest name-key from the agent_id
        # Format: bmad-agent-{module}-{name...}
        parts = agent_id.split("-")
        # parts[0]="bmad" parts[1]="agent" parts[2]=module parts[3..]=name
        if len(parts) < 4:
            continue
        module = parts[2]
        name_key = _AGENT_ID_TO_MANIFEST_KEY.get(agent_id, "-".join(parts[3:]))

        # Enrich from manifest
        meta = manifest_index.get(name_key, {})
        display_name = meta.get("displayName") or name_key.replace("-", " ").title()
        icon = meta.get("icon") or "🤖"
        role = meta.get("title") or ""
        description = meta.get("identity") or meta.get("capabilities") or ""

        workflow_keys = sorted(
            set(agent_workflow_map.get(agent_id, [])),
            key=lambda k: WORKFLOWS[k].label.lower() if k in WORKFLOWS else k,
        )

        category = "sprint" if module in _SPRINT_MODULES else "other"

        agent_def = AgentDef(
            name=display_name,
            persona=f"{display_name} {icon}",
            icon=icon,
            workflow_keys=workflow_keys,
            role=role,
            description=description,
            category=category,
            agent_id=agent_id,
        )

        if category == "sprint":
            sprint_agents.append(agent_def)
        else:
            other_agents.append(agent_def)

    if not sprint_agents and not other_agents:
        return list(AGENTS)

    # Sort: sprint by canonical order, other alphabetically by display name
    sprint_agents.sort(
        key=lambda a: _SPRINT_ORDER.index(a.name) if a.name in _SPRINT_ORDER else 999
    )
    other_agents.sort(key=lambda a: a.name)

    return sprint_agents + other_agents
