"""Golden stories for the Andes agents: simulated users vs draft, judged twice, noise-aware.

The stories in tests/orchestrate/golden/*.json are `orchestrate evaluations` test cases
(a simulated user follows `story`; tool calls and the final answer are checked) plus our
own `x_*` keys, which are removed before the evaluator sees them:

    x_db       what must be in Supabase afterwards (deterministic judge)
    x_seed     a stored profile the traveler must already have (returning traveler)
    x_holdout  never shown to the refinement loop; only counts in the gate
    x_text_anywhere  strings some answer must contain (instead of only the last one)

Dates are written relative to today in Colombia as {d+N}, so stories never go stale.

Every attempt of a story ends as one of:

    ok       the evaluator and the database judge both pass
    fail     the agent got it wrong
    invalid  the simulated user broke the test (wrote the assistant's text or tool-call
             JSON, or left after an ordinary question); the attempt is retried

Gate: a training story passes when it is ok in at least 2 of 3 rounds; a holdout story
must be ok in all 3. A story still invalid after its retries counts as not ok.

    python scripts/golden.py run --orchestrate <path>   # make wxo-eval
    python scripts/golden.py gate                       # reprint the gate from results.json
    python scripts/golden.py cleanup                    # delete every test+ traveler

Needs TOOLS_API_URL and TOOLS_API_KEY in the environment (all data access goes through the
tools API's key-protected /test-support routes, so it works on any network); never
prints them.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import re
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "orchestrate" / "golden"
BUILD = ROOT / "build" / "golden"
EVAL = ROOT / "build" / "eval"
RESULTS = EVAL / "results.json"
ENV_FILE = ROOT / "orchestrate" / "environment.yaml"
PREFIX = "test+golden-"
DATE_TOKEN = re.compile(r"\{d\+(\d+)\}")
INSURANCE_PER_PERSON = 180_000
SPANISH_HINTS = (" de ", " y ", " la ", " el ", " en ", " le ", " viaja")
ENGLISH_HINTS = (" the ", " and ", " is ", " traveler ")
ROUNDS = 3
RETRIES = 2
TRAIN_MIN_OK = 2
SIMULATED_USER = {
    # the default simulated user (llama-3-3-70b) ended conversations too early
    "model_id": "groq/openai/gpt-oss-120b",
    "user_response_style": [
        "Write in Colombian Spanish, short messages, like a real customer.",
        "Give only the facts your story allows, when the assistant asks for them.",
        "Give the e-mail from your story as soon as the assistant asks for it.",
        "Answer every question the assistant asks; if your story has no answer, "
        "say briefly that you do not know or do not need it.",
        "Do not end the conversation before your story's goal is reached; once it is "
        "reached, end it right away without small talk.",
        "Write only your own message, never the assistant's.",
    ],
}


# --------------------------------------------------------------------------- stories


def today_colombia(now: datetime | None = None) -> date:
    now = now or datetime.now(UTC)
    return (now - timedelta(hours=5)).date()


def fill_dates(node: Any, today: date) -> Any:
    """Replace every {d+N} with today + N days (ISO) in strings, recursively."""
    if isinstance(node, str):
        return DATE_TOKEN.sub(lambda m: (today + timedelta(days=int(m[1]))).isoformat(), node)
    if isinstance(node, list):
        return [fill_dates(n, today) for n in node]
    if isinstance(node, dict):
        return {k: fill_dates(v, today) for k, v in node.items()}
    return node


def load_stories(today: date) -> dict[str, dict[str, Any]]:
    return {
        p.stem: fill_dates(json.loads(p.read_text(encoding="utf-8")), today)
        for p in sorted(GOLDEN.glob("*.json"))
    }


def evaluator_case(name: str, story: dict[str, Any]) -> dict[str, Any]:
    case = {k: v for k, v in story.items() if not k.startswith("x_")}
    case["dataset_name"] = name
    return case


def traveler_of(story: dict[str, Any]) -> str:
    match = re.search(r"test\+golden-\d+@andes\.test", story["story"])
    if not match:
        raise ValueError("every story must name its test+golden-NN@andes.test traveler")
    return match[0]


def render(attempt: str, stories: dict[str, dict[str, Any]]) -> Path:
    """Write the evaluator cases and config of one attempt; returns the config path."""
    cases = BUILD / attempt
    cases.mkdir(parents=True, exist_ok=True)
    for old in cases.glob("*.json"):
        old.unlink()
    for name, story in stories.items():
        (cases / f"{name}.json").write_text(
            json.dumps(evaluator_case(name, story), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    env = yaml.safe_load(ENV_FILE.read_text())
    config = {
        "test_paths": [str(cases)],
        "auth_config": {"url": env["url"], "tenant_name": env["name"]},
        "output_dir": str(EVAL / attempt),
        "enable_verbose_logging": False,
        "n_runs": 1,
        "llm_user_config": SIMULATED_USER,
    }
    path = cases / "config.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True))
    return path


# --------------------------------------------------------------------------- database


def _api() -> tuple[str, dict[str, str]]:
    base = os.environ.get("TOOLS_API_URL", "").rstrip("/")
    key = os.environ.get("TOOLS_API_KEY", "")
    if not base or not key:
        sys.exit("TOOLS_API_URL and TOOLS_API_KEY must be set (put them in .env)")
    return base, {"X-API-Key": key}


def _post(path: str, body: dict) -> dict:
    """Test-support calls go through the tools API over HTTPS (works on any network)."""
    import httpx

    base, headers = _api()
    r = httpx.post(f"{base}{path}", headers=headers, json=body, timeout=120)
    r.raise_for_status()
    return r.json()


def delete_travelers(ids: list[str] | None = None) -> int:
    """Delete test travelers (ids that start with test+); None = all of them."""
    return int(_post("/test-support/reset", {"traveler_ids": ids})["deleted"])


def seed_profiles(stories: dict[str, dict[str, Any]]) -> int:
    import httpx

    base, headers = _api()
    seeded = 0
    for story in stories.values():
        seed = story.get("x_seed", {}).get("profile")
        if not seed:
            continue
        r = httpx.put(
            f"{base}/travelers/{traveler_of(story)}/profile",
            headers=headers,
            json={"consent_personalization": True, **seed},
            timeout=90,
        )
        if not r.json().get("ok"):
            sys.exit(f"could not seed {traveler_of(story)}: {r.text[:200]}")
        seeded += 1
    return seeded


def reset(stories: dict[str, dict[str, Any]]) -> None:
    """Fresh database state for these stories' travelers (deleted, then seeded)."""
    delete_travelers([traveler_of(s) for s in stories.values()])
    seed_profiles(stories)


def fetch_state(travelers: list[str]) -> dict[str, dict[str, Any]]:
    doc = _post("/test-support/state", {"traveler_ids": travelers})
    packages = {p["id"]: p for p in doc["packages"]}
    state = doc["travelers"]
    for st in state.values():
        for q in st["quotes"]:
            q["package"] = packages[q["package_id"]]
            q["start_date"] = date.fromisoformat(q["start_date"])
            q["end_date"] = date.fromisoformat(q["end_date"])
    return state


# --------------------------------------------------------------------------- judge


def quote_rule_errors(q: dict[str, Any]) -> list[str]:
    """Business rules every stored quote must follow, whatever the conversation was."""
    pkg = q["package"]
    errors = []
    days = (q["end_date"] - q["start_date"]).days + 1
    if days != pkg["duration_days"]:
        errors.append(
            f"quote {q['id']}: {days} days, package {pkg['name']} lasts {pkg['duration_days']}"
        )
    expected = pkg["rate_per_person"] * q["travelers"]
    if any("Seguro" in line.get("description", "") for line in q["lines"]):
        expected += INSURANCE_PER_PERSON * q["travelers"]
    if q["total_amount"] != expected:
        errors.append(f"quote {q['id']}: total {q['total_amount']} != expected {expected}")
    return errors


def looks_spanish(text: str) -> bool:
    t = f" {text.lower()} "
    return sum(h in t for h in SPANISH_HINTS) >= 2 and sum(h in t for h in ENGLISH_HINTS) < 2


def judge_story(expect: dict[str, Any], st: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for q in st["quotes"]:
        errors += quote_rule_errors(q)
    wanted = expect.get("quotes", [])
    if not wanted and st["quotes"]:
        errors.append(f"expected no quotes, found {len(st['quotes'])}")
    for w in wanted:
        hit = [
            q
            for q in st["quotes"]
            if q["start_date"].isoformat() == w["start_date"]
            and q["end_date"].isoformat() == w["end_date"]
            and q["travelers"] == w["travelers"]
            and q["total_amount"] == w["total"]
        ]
        if not hit:
            errors.append(f"missing quote {w}")
    n_res = expect.get("reservations", 0)
    if len(st["reservations"]) != n_res:
        errors.append(f"expected {n_res} reservations, found {len(st['reservations'])}")
    for r in st["reservations"]:
        if r["idempotency_key"] != f"res-{r['quote_id']}":
            errors.append(f"idempotency_key {r['idempotency_key']!r} is not res-<quote_id>")
    want_profile = expect.get("profile")
    profile = st["profile"]
    stored = bool(profile and profile["consent_personalization"])
    if want_profile is None and stored:
        errors.append("a profile was stored without consent")
    if want_profile:
        if not stored:
            errors.append("expected a stored profile with consent")
        elif not (profile.get("persona_prompt") or "").strip():
            errors.append("stored profile has no persona_prompt")
        elif want_profile.get("persona_spanish") and not looks_spanish(profile["persona_prompt"]):
            errors.append(f"persona_prompt is not in Spanish: {profile['persona_prompt'][:80]!r}")
    if st["handoffs"] < expect.get("handoffs", 0):
        errors.append(f"expected {expect['handoffs']} handoff(s), found {st['handoffs']}")
    return errors


def judge(stories: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    travelers = {name: traveler_of(s) for name, s in stories.items()}
    state = fetch_state(list(travelers.values()))
    return {
        name: judge_story(s.get("x_db", {}), state[travelers[name]]) for name, s in stories.items()
    }


# --------------------------------------------------------------------------- simulator noise

ASSISTANT_MARKUP = re.compile(r"(\*\*[^*]+\*\*|^#{1,3} |\|\s*-{3,}|^\s*\d+\.\s+\*\*)", re.M)


def _text(content: Any) -> str:
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)


def simulator_problem(messages: list[dict[str, Any]], passed: bool) -> str | None:
    """Why the simulated user, not the agent, broke this conversation (None if it did not).

    The simulated user is an LLM: it sometimes writes the assistant's answer or tool-call
    JSON into its own turn, or answers END right after an ordinary question. Those runs
    test nothing, so they are retried instead of counted as agent failures.
    """
    for m in messages:
        if m.get("role") != "user" or (m.get("type") or "text") != "text":
            continue
        text = _text(m.get("content"))
        if '"tool_call"' in text or '"tool_response"' in text or '{"type"' in text:
            return "the simulated user wrote tool-call JSON"
        if len(text) > 400 or ASSISTANT_MARKUP.search(text):
            return "the simulated user wrote the assistant's text"
    if not passed and messages:
        last = messages[-1]
        if (
            last.get("role") == "assistant"
            and (last.get("type") or "text") == "text"
            and _text(last.get("content")).rstrip().endswith("?")
            and not any(
                m.get("type") == "tool_call" and "escalar" in _text(m.get("content"))
                for m in messages
            )
        ):
            return "the simulated user left after an ordinary question"
    return None


# --------------------------------------------------------------------------- runs


def _latest(attempt_dir: Path) -> Path | None:
    found = sorted(p for p in attempt_dir.glob("*/") if (p / "summary_metrics.csv").exists())
    return found[-1] if found else None


def _evaluator_results(attempt_dir: Path) -> tuple[dict[str, dict], Path | None]:
    latest = _latest(attempt_dir)
    if not latest:
        return {}, None
    with (latest / "summary_metrics.csv").open(newline="") as f:
        return {r["dataset_name"]: r for r in csv.DictReader(f)}, latest


def evaluator_ok(row: dict | None, story: dict[str, Any], messages: list[dict]) -> bool:
    """The evaluator's verdict, except for its text check on the LAST message.

    The simulated user often keeps talking after its goal ("solo la recomendación"), so
    the last answer is a goodbye. A story with x_text_anywhere passes the text check when
    every expected tool call happened and some answer shown to the traveler contains all
    of those strings.
    """
    if not row:
        return False
    if row.get("is_success") == "True":
        return True
    wanted = story.get("x_text_anywhere")
    if not wanted:
        return False
    tools_ok = row.get("missed_tool_calls") in ("0", "0.0") and row.get(
        "correct_tool_calls"
    ) == row.get("expected_tool_calls")
    shown = " ".join(
        _text(m.get("content"))
        for m in messages
        if m.get("role") == "assistant" and (m.get("type") or "text") in VISIBLE
    ).lower()
    return tools_ok and all(w.lower() in shown for w in wanted)


def _messages(run_dir: Path | None, name: str) -> list[dict[str, Any]]:
    path = run_dir / "messages" / f"{name}.messages.json" if run_dir else None
    return json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else []


AMOUNT = re.compile(r"(\$\s?\d|\bCOP\b|\bUSD\b|\d{1,3}([.\s]\d{3}){2,})", re.I)
VISIBLE = {"text", "conversational_search"}


def critical_problem(messages: list[dict[str, Any]]) -> str | None:
    """Mistakes no average may hide: an amount shown before any real quote.

    Every price the traveler sees must come from a "Cotizar paquete" result earlier in
    the conversation; anything else is an invented price (it happened with a made-up
    "12.600.000 COP, válida por 48 horas"). Counts even when the simulated user misbehaved.
    """
    quoted = False
    for m in messages:
        kind = m.get("type") or "text"
        content = m.get("content")
        if kind == "tool_response" and isinstance(content, str):
            with contextlib.suppress(ValueError):  # stored as serialized JSON
                content = json.loads(content)
        if kind == "tool_response" and isinstance(content, dict):
            if str(content.get("name", "")).startswith("cotizar_paquete"):
                body = _text(content.get("content"))
                quoted = quoted or bool(re.search(r'"ok":\s*true', body))
        elif m.get("role") == "assistant" and kind in VISIBLE and not quoted:
            hit = AMOUNT.search(_text(content))
            if hit:
                return f"amount {hit[0]!r} shown before any quote"
    return None


def classify(evaluator_ok: bool, db_errors: list[str], problem: str | None) -> str:
    if evaluator_ok and not db_errors:
        return "ok"
    return "invalid" if problem else "fail"


def attempt(orchestrate: str, label: str, stories: dict[str, dict[str, Any]]) -> dict[str, dict]:
    reset(stories)
    config = render(label, stories)
    log = BUILD / label / "evaluate.log"
    with log.open("w") as out:
        code = subprocess.run(
            [orchestrate, "evaluations", "evaluate", "-c", str(config)],
            stdout=out,
            stderr=subprocess.STDOUT,
            check=False,
        ).returncode
    if code != 0:
        sys.exit(f"orchestrate evaluations failed ({label}); see {log.relative_to(ROOT)}")
    evaluator, run_dir = _evaluator_results(EVAL / label)
    db = judge(stories)
    results = {}
    for name in stories:
        messages = _messages(run_dir, name)
        ok = evaluator_ok(evaluator.get(name), stories[name], messages)
        problem = simulator_problem(messages, ok and not db[name])
        results[name] = {
            "critical": critical_problem(messages),
            "attempt": label,
            "run_dir": str(run_dir.relative_to(EVAL)) if run_dir else None,
            "evaluator": ok,
            "db": db[name],
            "problem": problem,
            "status": classify(ok, db[name], problem),
        }
    return results


def run(orchestrate: str, today: date, rounds: int = ROUNDS, retries: int = RETRIES) -> dict:
    stories = load_stories(today)
    results: dict[str, list[list[dict]]] = {name: [] for name in stories}
    for rnd in range(1, rounds + 1):
        pending = dict(stories)
        for n in range(retries + 1):
            label = f"r{rnd}a{n + 1}"
            print(f"== round {rnd}, attempt {n + 1}: {len(pending)} story(ies)")
            for name, res in attempt(orchestrate, label, pending).items():
                if n == 0:
                    results[name].append([])
                results[name][-1].append(res)
                print(
                    f"   {res['status']:<8} {name}"
                    + (f"  ({res['problem']})" if res["problem"] else "")
                )
            pending = {
                k: v for k, v in pending.items() if results[k][-1][-1]["status"] == "invalid"
            }
            if not pending:
                break
    doc = {"today": today.isoformat(), "rounds": rounds, "results": results}
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(doc, ensure_ascii=False, indent=2, default=str))
    return doc


# --------------------------------------------------------------------------- gate


def final_status(attempts: list[dict]) -> str:
    """A round's verdict is its last attempt (earlier ones were invalid)."""
    return attempts[-1]["status"] if attempts else "fail"


def gate_rows(doc: dict, stories: dict[str, dict[str, Any]]) -> tuple[list[dict], bool]:
    rows, ok_all = [], True
    for name, rounds in doc["results"].items():
        holdout = bool(stories.get(name, {}).get("x_holdout"))
        statuses = [final_status(r) for r in rounds]
        oks = statuses.count("ok")
        need = len(rounds) if holdout else min(TRAIN_MIN_OK, len(rounds))
        critical = [a["critical"] for r in rounds for a in r if a.get("critical")]
        passed = oks >= need and not critical
        ok_all = ok_all and passed
        rows.append(
            {
                "story": name,
                "holdout": holdout,
                "statuses": statuses,
                "passed": passed,
                "need": need,
                "critical": critical,
                "invalid_attempts": sum(a["status"] == "invalid" for r in rounds for a in r),
                # every attempt, for the refinement report (transcripts only for training stories)
                "runs": [
                    {
                        "run": a["run_dir"],
                        "attempt": a["attempt"],
                        "evaluator": a["evaluator"],
                        "db": a["db"],
                        "problem": a["problem"],
                        "status": a["status"],
                        "critical": a.get("critical"),
                    }
                    for r in rounds
                    for a in r
                ],
            }
        )
    return rows, ok_all


def add_critical(doc: dict) -> None:
    """Results saved before the critical check existed: compute it from the transcripts."""
    for rounds in doc["results"].values():
        for a in (a for r in rounds for a in r):
            if "critical" not in a:
                run_dir = EVAL / a["run_dir"] if a.get("run_dir") else None
                a["critical"] = critical_problem(_messages(run_dir, a.get("story", "")))


def print_gate(doc: dict, today: date) -> bool:
    for name, rounds in doc["results"].items():
        for a in (a for r in rounds for a in r):
            a.setdefault("story", name)
    add_critical(doc)
    rows, ok = gate_rows(doc, load_stories(today))
    (EVAL / "gate.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
    for row in rows:
        marks = " ".join(row["statuses"])
        tag = "holdout " if row["holdout"] else ""
        noise = f"  ({row['invalid_attempts']} invalid retried)" if row["invalid_attempts"] else ""
        verdict = "PASS" if row["passed"] else "FAIL"
        print(f"  {verdict} {row['story']:<32} {tag}{marks}  need {row['need']} ok{noise}")
        for c in row["critical"]:
            print(f"       CRITICAL: {c}")
    print("golden gate:", "PASS" if ok else "FAIL")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run", "gate", "cleanup"])
    parser.add_argument("--orchestrate", default="orchestrate", help="path to the ADK CLI")
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    args = parser.parse_args()
    today = today_colombia()
    if args.command == "cleanup":
        print(f"deleted {delete_travelers(None)} test traveler(s)")
        return 0
    if args.command == "run":
        doc = run(args.orchestrate, today, rounds=args.rounds)
    else:
        if not RESULTS.exists():
            sys.exit("no results yet: make wxo-eval")
        doc = json.loads(RESULTS.read_text(encoding="utf-8"))
    return 0 if print_gate(doc, today) else 1


if __name__ == "__main__":
    raise SystemExit(main())
