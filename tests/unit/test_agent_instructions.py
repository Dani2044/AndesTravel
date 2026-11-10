"""The versioned agents stay inside orchestrate/scope.yaml (tools, budget, fixed phrases)."""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
SCOPE = yaml.safe_load((REPO / "orchestrate" / "scope.yaml").read_text(encoding="utf-8"))
AGENTS = {
    a["name"]: a
    for a in (
        yaml.safe_load(f.read_text(encoding="utf-8"))
        for f in sorted((REPO / "orchestrate" / "agents").glob("*.yaml"))
    )
}


def test_every_agent_tool_is_in_scope_and_assigned_to_it() -> None:
    for name, agent in AGENTS.items():
        for tool in agent.get("tools") or []:
            assert tool in SCOPE["tools"], f"{name} uses {tool}, which is not in scope.yaml"
            assert name in SCOPE["tools"][tool], f"{tool} is not allowed for {name}"
        for kb in agent.get("knowledge_base") or []:
            assert name in SCOPE["knowledge_bases"].get(kb, []), f"{name} uses KB {kb}"


def test_every_scope_tool_is_wired() -> None:
    wired = {t for a in AGENTS.values() for t in a.get("tools") or []}
    assert set(SCOPE["tools"]) == wired


@pytest.mark.parametrize("name", sorted(AGENTS))
def test_instructions_fit_the_budget(name: str) -> None:
    limits = SCOPE["max_instruction_chars"]
    size = len(AGENTS[name].get("instructions") or "")
    assert size <= limits.get(name, limits["default"]), f"{name}: {size} chars"


def test_fixed_phrases_stay_in_the_instructions() -> None:
    for name, phrases in SCOPE["fixed_phrases"].items():
        for phrase in phrases:
            assert phrase in AGENTS[name]["instructions"], f"{name} lost: {phrase}"
