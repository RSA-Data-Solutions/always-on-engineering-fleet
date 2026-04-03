#!/usr/bin/env python3
"""
Fleet self-validation script.
Checks agent files, context files, and cross-references for consistency.
Output format matches run_tests.py: PASS [name] / FAIL [name]: reason
"""

import os
import sys

FLEET_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REQUIRED_AGENT_FILES = [
    "agents/cto.md",
    "agents/qa-engineer.md",
    "agents/software-engineer.md",
    "agents/dhira.md",
]

REQUIRED_CONTEXT_FILES = [
    "contexts/ibmimcp.md",
    "contexts/inova.md",
    "contexts/self-improvement.md",
]

REQUIRED_ROOT_FILES = [
    "SKILL.md",
    "CLAUDE.md",
    "README.md",
    ".gitignore",
]

# Strings that must appear somewhere in each context file.
# Use the actual text from the markdown (headings or table cell text).
CONTEXT_REQUIRED_STRINGS = [
    ("Repo path",            "Repo path field (table row or heading)"),
    ("test_command",         "test_command field"),
    ("push_remote",          "push_remote field"),
    ("Research communities", "Research communities section"),
    ("Human scope",          "Human scope section"),
]

AGENT_REQUIRED_SECTIONS = {
    "agents/cto.md": [
        "## On start",
        "## The main loop",
        "## Budget awareness",
        "## Git safety",
    ],
    "agents/qa-engineer.md": [
        "## Inputs",
        "## Your job",
        "## What not to do",
    ],
    "agents/software-engineer.md": [
        "## Inputs",
        "## Your job",
        "## What not to do",
    ],
    "agents/dhira.md": [
        "## Research process",
        "## Proposal format",
        "## What not to do",
    ],
}

passed = 0
failed = 0


def check(name, condition, reason=""):
    global passed, failed
    if condition:
        print(f"PASS [{name}]")
        passed += 1
    else:
        print(f"FAIL [{name}]: {reason}")
        failed += 1


def file_exists(rel_path):
    return os.path.isfile(os.path.join(FLEET_ROOT, rel_path))


def read_file(rel_path):
    path = os.path.join(FLEET_ROOT, rel_path)
    if not os.path.isfile(path):
        return ""
    with open(path) as f:
        return f.read()


# --- Required files exist ---
for f in REQUIRED_ROOT_FILES:
    check(f"root_file:{f}", file_exists(f), f"{f} is missing")

for f in REQUIRED_AGENT_FILES:
    check(f"agent_file:{f}", file_exists(f), f"{f} is missing")

for f in REQUIRED_CONTEXT_FILES:
    check(f"context_file:{f}", file_exists(f), f"{f} is missing")

# --- Agent files have required sections ---
for agent_file, sections in AGENT_REQUIRED_SECTIONS.items():
    content = read_file(agent_file)
    for section in sections:
        label = section.strip("# ").replace(" ", "_")
        check(
            f"section:{agent_file.split('/')[-1]}:{label}",
            section in content,
            f"'{section}' not found in {agent_file}"
        )

# --- Context files have required strings ---
for ctx_file in REQUIRED_CONTEXT_FILES:
    content = read_file(ctx_file)
    short = ctx_file.split("/")[-1].replace(".md", "")
    for string, description in CONTEXT_REQUIRED_STRINGS:
        check(
            f"context:{short}:{string.replace(' ', '_')}",
            string in content,
            f"'{string}' ({description}) not found in {ctx_file}"
        )

# --- SKILL.md references all context files ---
skill_content = read_file("SKILL.md")
for ctx in ["ibmimcp", "inova", "self-improvement"]:
    check(
        f"skill_references:{ctx}",
        ctx in skill_content,
        f"contexts/{ctx}.md not referenced in SKILL.md"
    )

# --- CLAUDE.md references all context files ---
claude_content = read_file("CLAUDE.md")
for ctx in ["ibmimcp", "inova", "self-improvement"]:
    check(
        f"claude_references:{ctx}",
        ctx in claude_content,
        f"contexts/{ctx}.md not referenced in CLAUDE.md"
    )

# --- CTO references all agent files ---
cto_content = read_file("agents/cto.md")
for agent in ["qa-engineer.md", "software-engineer.md", "dhira.md"]:
    check(
        f"cto_references:{agent}",
        agent in cto_content,
        f"{agent} not referenced in agents/cto.md"
    )

# --- fleet-workspace/proposals/index.md exists ---
check(
    "fleet_workspace:proposals_index",
    file_exists("fleet-workspace/proposals/index.md"),
    "fleet-workspace/proposals/index.md is missing"
)

# --- Summary ---
print(f"\nRESULTS: {passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
