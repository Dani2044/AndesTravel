"""Collect what failed in the last runs into build/refine/report.md for the critic.

Reads the golden gate (build/eval/gate.json + the evaluator transcripts), the
adversarial results (build/adversarial/results.json) and, if present, the evaluator's
analysis (build/eval/analyze.txt). Holdout cases appear only as pass/fail, never with
their conversation, so fixes cannot be tailored to them.

The critic (Claude Code in the PoC) reads the report and proposes, within
orchestrate/scope.yaml: instruction diffs, tool/API changes and new inputs for the
knowledge base or the database. Anything out of scope goes to docs/backlog.md.
A human approves before any push.

    python scripts/refine_report.py        # make wxo-refine
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "build" / "eval"
ADV = ROOT / "build" / "adversarial" / "results.json"
OUT = ROOT / "build" / "refine" / "report.md"
AGENTS = ROOT / "orchestrate" / "agents"
MAX_TURN_CHARS = 700


def _short(text: Any) -> str:
    if isinstance(text, (dict, list)):
        text = json.dumps(text, ensure_ascii=False)
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_TURN_CHARS else text[:MAX_TURN_CHARS] + " …"


def transcript(run: str, story: str) -> list[str]:
    files = sorted((EVAL / run).glob(f"*/messages/{story}.messages.json"))
    if not files:
        return ["(no transcript)"]
    lines = []
    for m in json.loads(files[-1].read_text(encoding="utf-8")):
        kind = m.get("type") or "text"
        lines.append(f"- **{m.get('role')}/{kind}**: {_short(m.get('content'))}")
    return lines


def golden_section() -> list[str]:
    gate = EVAL / "gate.json"
    if not gate.exists():
        return ["_No golden run yet (make wxo-eval)._"]
    out = []
    for row in json.loads(gate.read_text(encoding="utf-8")):
        fails = [r for r in row["runs"] if not (r["evaluator"] and not r["db"])]
        status = "PASS" if not fails else f"FAIL in {len(fails)}/{len(row['runs'])} runs"
        out.append(f"### {row['story']}{' (holdout)' if row['holdout'] else ''}: {status}")
        if not fails or row["holdout"]:
            continue
        for r in fails:
            out.append(f"**{r['run']}**: evaluator {'ok' if r['evaluator'] else 'FAIL'}")
            out += [f"- db: {e}" for e in r["db"]]
            out.append("")
            out += transcript(r["run"], row["story"])
            out.append("")
    return out


def adversarial_section() -> list[str]:
    if not ADV.exists():
        return ["_No adversarial run yet (make test-adversarial)._"]
    doc = json.loads(ADV.read_text(encoding="utf-8"))
    results = doc.get("results", {}).get("results", [])
    out = []
    for r in results:
        if r.get("success") and not r.get("error"):
            continue
        meta = (r.get("testCase") or {}).get("metadata") or {}
        v = r.get("vars") or {}
        head = f"### adv-{v.get('case', '?')} [{meta.get('category', '?')}]"
        if meta.get("holdout"):
            out.append(head + " (holdout): FAIL")
            continue
        reason = (r.get("gradingResult") or {}).get("reason") or r.get("error") or ""
        answer = (r.get("response") or {}).get("output", "")
        out += [
            head,
            f"- attack: {_short(v.get('attack'))}",
            f"- answer: {_short(answer)}",
            f"- why: {_short(reason)}",
            "",
        ]
    passed = sum(1 for r in results if r.get("success") and not r.get("error"))
    return [f"{passed}/{len(results)} passed.", ""] + (out or ["Nothing failed."])


def budget_section() -> list[str]:
    scope = yaml.safe_load((ROOT / "orchestrate" / "scope.yaml").read_text(encoding="utf-8"))
    limits = scope["max_instruction_chars"]
    out = ["| agent | chars | budget |", "|---|---|---|"]
    for f in sorted(AGENTS.glob("*.yaml")):
        a = yaml.safe_load(f.read_text(encoding="utf-8"))
        n = len(a.get("instructions") or "")
        budget = limits.get(a["name"], limits["default"])
        out.append(f"| {a.get('display_name')} ({a['name']}) | {n} | {budget} |")
    return out


def main() -> int:
    analyze = EVAL / "analyze.txt"
    parts = [
        "# Refinement report",
        "",
        "Propose changes only inside `orchestrate/scope.yaml`; anything else goes to "
        "`docs/backlog.md`. Holdout cases show only pass/fail on purpose.",
        "",
        "## Golden stories",
        *golden_section(),
        "",
        "## Adversarial",
        *adversarial_section(),
        "",
        "## Instruction budget",
        *budget_section(),
        "",
        "## Evaluator analysis",
        analyze.read_text(encoding="utf-8")[-6000:] if analyze.exists() else "_not run_",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
