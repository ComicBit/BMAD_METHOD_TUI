"""Dynamic agent and workflow discovery from BMAD installations."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import AgentDef, Model, WorkflowDef


@dataclass
class DiscoveredWorkflow:
    """A workflow discovered from skill manifest."""
    skill_id: str          # e.g., "bmad-dev-story"
    name: str              # e.g., "bmad-dev-story"
    description: str       # from manifest
    module: str            # e.g., "bmm", "tea", "core"
    path: str              # relative path to skill


def load_skill_manifest(project_root: Path) -> list[DiscoveredWorkflow]:
    """Parse _bmad/_config/skill-manifest.csv and return discovered workflows."""
    manifest_path = project_root / "_bmad" / "_config" / "skill-manifest.csv"
    if not manifest_path.exists():
        return []
    
    workflows = []
    try:
        with manifest_path.open('r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                skill_id = row.get('canonicalId', '').strip('"')
                name = row.get('name', '').strip('"')
                description = row.get('description', '').strip('"')
                module = row.get('module', '').strip('"')
                path = row.get('path', '').strip('"')
                
                if skill_id and name:
                    workflows.append(DiscoveredWorkflow(
                        skill_id=skill_id,
                        name=name,
                        description=description,
                        module=module,
                        path=path,
                    ))
    except Exception as e:
        print(f"Warning: Failed to parse skill manifest: {e}")
    
    return workflows


def parse_agent_file(agent_path: Path) -> dict[str, str]:
    """Extract agent metadata from a _bmad agent .md file.
    
    Returns dict with: name, icon, role, identity, agent_id
    """
    try:
        content = agent_path.read_text(encoding='utf-8')
        
        # Parse XML-style agent tag attributes
        agent_match = re.search(r'<agent[^>]+id="([^"]*)"[^>]+name="([^"]*)"[^>]+title="([^"]*)"[^>]+icon="([^"]*)"', content)
        if not agent_match:
            # Try alternative order
            agent_match = re.search(r'<agent[^>]+name="([^"]*)"[^>]+title="([^"]*)"[^>]+icon="([^"]*)"', content)
            if agent_match:
                name = agent_match.group(1)
                role = agent_match.group(2)
                icon = agent_match.group(3)
                agent_id = ""
            else:
                return {}
        else:
            agent_id = agent_match.group(1)
            name = agent_match.group(2)
            role = agent_match.group(3)
            icon = agent_match.group(4)
        
        # Extract identity from persona section
        identity_match = re.search(r'<identity>([^<]+)</identity>', content)
        identity = identity_match.group(1).strip() if identity_match else ""
        
        # Extract menu items with exec="skill:xxx"
        menu_skills = re.findall(r'exec="skill:([^"]+)"', content)
        
        return {
            'name': name,
            'icon': icon,
            'role': role,
            'identity': identity,
            'agent_id': agent_id,
            'menu_skills': menu_skills,
        }
    except Exception as e:
        print(f"Warning: Failed to parse agent file {agent_path}: {e}")
        return {}


def discover_agents_from_files(project_root: Path, workflows: list[DiscoveredWorkflow]) -> list[AgentDef]:
    """Discover agents by parsing _bmad/{module}/agents/*.md files."""
    agents = []
    bmad_dir = project_root / "_bmad"
    
    if not bmad_dir.exists():
        return []
    
    # Map skill IDs to workflow keys (strip "bmad-" prefix)
    skill_to_workflow = {wf.skill_id: wf.skill_id.replace('bmad-', '') for wf in workflows}
    
    # Scan each module for agent files
    for module_dir in bmad_dir.iterdir():
        if not module_dir.is_dir() or module_dir.name.startswith('_'):
            continue
        
        agents_dir = module_dir / "agents"
        if not agents_dir.exists():
            continue
        
        for agent_file in agents_dir.glob("*.md"):
            if agent_file.name.startswith('.'):
                continue
            
            agent_data = parse_agent_file(agent_file)
            if not agent_data.get('name'):
                continue
            
            # Convert menu skills to workflow keys
            workflow_keys = []
            for skill_id in agent_data.get('menu_skills', []):
                workflow_key = skill_to_workflow.get(skill_id, skill_id.replace('bmad-', ''))
                workflow_keys.append(workflow_key)
            
            # Derive agent_id from file name and module
            file_stem = agent_file.stem  # e.g., "sm", "dev", "architect"
            agent_id = f"bmad-agent-{module_dir.name}-{file_stem}"
            
            # Determine category (sprint vs other)
            category = "sprint" if module_dir.name in ["bmm", "tea"] else "other"
            
            agents.append(AgentDef(
                name=agent_data['name'],
                persona=f"{agent_data['name']} ({agent_data['role']}) {agent_data['icon']}",
                icon=agent_data['icon'],
                workflow_keys=workflow_keys,
                role=agent_data['role'],
                description=agent_data.get('identity', ''),
                category=category,
                agent_id=agent_id,
            ))
    
    return agents


def discover_workflows_dict(project_root: Path, workflows: list[DiscoveredWorkflow]) -> dict[str, WorkflowDef]:
    """Create WORKFLOWS dict entries for discovered workflows."""
    workflows_dict = {}
    
    for wf in workflows:
        workflow_key = wf.skill_id.replace('bmad-', '')
        
        # Derive agent ID from skill ID
        # e.g., bmad-dev-story → bmad-agent-bmm-dev (guess based on module)
        if wf.module == "bmm":
            agent_id = "bmad-agent-bmm-dev"  # default to dev agent
        elif wf.module == "tea":
            agent_id = "bmad-agent-tea-tea"
        elif wf.module == "cis":
            agent_id = "bmad-agent-cis"
        elif wf.module == "bmb":
            agent_id = "bmad-agent-bmb"
        elif wf.module == "core":
            agent_id = "bmad-agent-bmad-master"
        else:
            agent_id = f"bmad-agent-{wf.module}"
        
        # Infer phase from module
        phase_map = {
            'bmm': 'Implementation',
            'tea': 'QA',
            'cis': 'Creative & Meta',
            'bmb': 'Creative & Meta',
            'core': 'Creative & Meta',
        }
        bmad_phase = phase_map.get(wf.module, 'Implementation')
        
        # Create workflow definition
        workflows_dict[workflow_key] = WorkflowDef(
            label=wf.name.replace('bmad-', '').replace('-', ' ').title(),
            agent=agent_id,
            persona=f"Agent {wf.module.upper()}",
            default_model=Model.SONNET,
            prompt_template=(
                "IMPORTANT: YOU ARE FORBIDDEN FROM SHOWING THE MENU. "
                "PROCEED IMMEDIATELY WITHOUT ANY PROMPTS OR QUESTIONS.\n"
                f"Run the {wf.name} workflow.\n"
                "Sprint status: {sprint_status_path}"
            ),
            description=wf.description,
            bmad_phase=bmad_phase,
        )
    
    return workflows_dict


def discover_agents(project_root: Path) -> tuple[list[AgentDef], dict[str, WorkflowDef]]:
    """Main discovery function: returns (agents, workflows) from BMAD installation.
    
    Returns empty lists if not a BMAD project or discovery fails.
    """
    try:
        # Step 1: Load skill manifest
        workflows = load_skill_manifest(project_root)
        if not workflows:
            return [], {}
        
        # Step 2: Discover agents from agent files
        agents = discover_agents_from_files(project_root, workflows)
        
        # Step 3: Create workflow definitions
        workflows_dict = discover_workflows_dict(project_root, workflows)
        
        return agents, workflows_dict
    
    except Exception as e:
        print(f"Agent discovery failed: {e}")
        return [], {}


def merge_agents_with_manual(
    discovered: list[AgentDef],
    manual: list[AgentDef]
) -> list[AgentDef]:
    """Merge discovered agents with manual overrides, preserving manual display order.
    
    Strategy:
    - Use manual list as the order template
    - Replace each manual agent with its discovered version (if exists)
    - Append any discovered agents not found in manual
    
    This preserves the curated display order while using discovered data.
    """
    if not discovered:
        return manual
    
    # Index discovered agents by agent_id for fast lookup
    discovered_by_id = {agent.agent_id: agent for agent in discovered}
    
    result = []
    
    # For each manual agent, use discovered version if available (preserves order)
    for manual_agent in manual:
        if manual_agent.agent_id in discovered_by_id:
            result.append(discovered_by_id[manual_agent.agent_id])
        else:
            result.append(manual_agent)
    
    # Append any discovered agents not in manual
    manual_ids = {agent.agent_id for agent in manual}
    for agent in discovered:
        if agent.agent_id not in manual_ids:
            result.append(agent)
    
    return result


def merge_workflows_with_manual(
    discovered: dict[str, WorkflowDef],
    manual: dict[str, WorkflowDef]
) -> dict[str, WorkflowDef]:
    """Merge discovered workflows with manual overrides.
    
    Manual workflows take priority (for backward compat and customization).
    """
    if not discovered:
        return manual
    
    # Start with discovered, override with manual
    result = dict(discovered)
    result.update(manual)
    
    return result
