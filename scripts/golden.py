"""Golden stories for the Andes agents: render, reset test data, judge in the database, gate.

The stories in tests/orchestrate/golden/*.json are `orchestrate evaluations` test cases
(a simulated user follows `story`; tool calls and the final answer are checked) plus our
own `x_*` keys, which are removed before the evaluator sees them:

    x_db       what must be in Supabase afterwards (deterministic judge)
    x_seed     a stored profile the traveler must already have (returning traveler)
    x_holdout  never shown to the refinement loop; only counts in the gate

Dates are written relative to today in Colombia as {d+N}, so stories never go stale.

    python scripts/golden.py render --run 1   # build/golden/run1/*.json + config.yaml
    python scripts/golden.py reset            # delete test+golden-* travelers, seed x_seed
    python scripts/golden.py judge --run 1    # check x_db + price/length rules -> judge.json
    python scripts/golden.py gate             # every story must pass the evaluator and judge
    python scripts/golden.py cleanup          # delete every test+ traveler (golden and adversarial)

make wxo-eval runs it all (see Makefile). Needs TOOLS_DATABASE_URL, TOOLS_API_URL and
TOOLS_API_KEY in the environment; never prints them.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "orchestrate" / "golden"
BUILD = ROOT / "build" / "golden"
EVAL = ROOT / "build" / "eval"
ENV_FILE = ROOT / "orchestrate" / "environment.yaml"
PREFIX = "test+golden-"
DATE_TOKEN = re.compile(r"\{d\+(\d+)\}")
INSURANCE_PER_PERSON = 180_000
SPANISH_HINTS = (" de ", " y ", " la ", " el ", " en ", " le ", " viaja")
ENGLISH_HINTS = (" the ", " and ", " is ", " traveler ")


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


def render(run: int, today: date) -> Path:
    out = BUILD / f"run{run}"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.json"):
        old.unlink()
    for name, story in load_stories(today).items():
        (out / f"{name}.json").write_text(
            json.dumps(evaluator_case(name, story), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    env = yaml.safe_load(ENV_FILE.read_text())
    config = {
        "test_paths": [str(out)],
        "auth_config": {"url": env["url"], "tenant_name": env["name"]},
        "output_dir": str(EVAL / f"run{run}"),
        "enable_verbose_logging": False,
        "n_runs": 1,
        "llm_user_config": {
            "user_response_style": [
                "Write in Colombian Spanish, short messages, like a real customer.",
                "Give only the facts your story allows, when the assistant asks for them.",
                # the simulated user drifted in the first runs: these keep it on its story
                "Give the e-mail from your story as soon as the assistant asks for it.",
                "Answer every question the assistant asks; if your story has no answer, "
                "say briefly that you do not know or do not need it.",
                "Do not end the conversation before your story's goal is reached; once it is "
                "reached, end it right away without small talk.",
                "Write only your own message, never the assistant's.",
            ]
        },
    }
    (out / "config.yaml").write_text(yaml.safe_dump(config, allow_unicode=True))
    return out


# --------------------------------------------------------------------------- database


def _db_url() -> str:
    url = os.environ.get("TOOLS_DATABASE_URL", "")
    if not url:
        sys.exit("TOOLS_DATABASE_URL is not set (put it in .env)")
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _connect() -> Any:
    import asyncpg

    return await asyncpg.connect(_db_url(), statement_cache_size=0, timeout=30)


async def delete_travelers(prefix: str) -> int:
    conn = await _connect()
    try:
        # profiles, quotes, reservations and handoffs cascade from travelers
        status = await conn.execute("delete from travelers where id like $1", prefix + "%")
    finally:
        await conn.close()
    return int(status.split()[-1])


def seed_profiles(stories: dict[str, dict[str, Any]]) -> int:
    import httpx

    base = os.environ.get("TOOLS_API_URL", "").rstrip("/")
    key = os.environ.get("TOOLS_API_KEY", "")
    if not base or not key:
        sys.exit("TOOLS_API_URL and TOOLS_API_KEY must be set to seed profiles")
    seeded = 0
    for story in stories.values():
        seed = story.get("x_seed", {}).get("profile")
        if not seed:
            continue
        r = httpx.put(
            f"{base}/travelers/{traveler_of(story)}/profile",
            headers={"X-API-Key": key},
            json={"consent_personalization": True, **seed},
            timeout=90,
        )
        if not r.json().get("ok"):
            sys.exit(f"could not seed {traveler_of(story)}: {r.text[:200]}")
        seeded += 1
    return seeded


async def fetch_state(travelers: list[str]) -> dict[str, dict[str, Any]]:
    conn = await _connect()
    try:
        packages = {
            str(r["id"]): dict(r)
            for r in await conn.fetch(
                "select id, name, duration_days, rate_per_person from packages"
            )
        }
        state: dict[str, dict[str, Any]] = {}
        for tid in travelers:
            quotes = [
                dict(r)
                for r in await conn.fetch(
                    "select id, package_id, start_date, end_date, travelers, lines, total_amount "
                    "from quotes where traveler_id = $1",
                    tid,
                )
            ]
            for q in quotes:
                q["package"] = packages[str(q["package_id"])]
                if isinstance(q["lines"], str):
                    q["lines"] = json.loads(q["lines"])
            reservations = [
                dict(r)
                for r in await conn.fetch(
                    "select quote_id, idempotency_key, status from reservations "
                    "where traveler_id = $1",
                    tid,
                )
            ]
            profile = await conn.fetchrow(
                "select consent_personalization, attributes, persona_prompt "
                "from traveler_profiles where traveler_id = $1",
                tid,
            )
            handoffs = await conn.fetchval(
                "select count(*) from handoffs where traveler_id = $1", tid
            )
            state[tid] = {
                "quotes": quotes,
                "reservations": reservations,
                "profile": dict(profile) if profile else None,
                "handoffs": handoffs,
            }
        return state
    finally:
        await conn.close()


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


def judge(run: int, today: date) -> dict[str, list[str]]:
    stories = load_stories(today)
    travelers = {name: traveler_of(s) for name, s in stories.items()}
    state = asyncio.run(fetch_state(list(travelers.values())))
    result = {
        name: judge_story(s.get("x_db", {}), state[travelers[name]]) for name, s in stories.items()
    }
    out = EVAL / f"run{run}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "judge.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


# --------------------------------------------------------------------------- gate


def latest_summary(run_dir: Path) -> Path | None:
    found = sorted(run_dir.glob("*/summary_metrics.csv"))
    return found[-1] if found else None


def eval_success(summary: Path) -> dict[str, bool]:
    with summary.open(newline="") as f:
        return {row["dataset_name"]: row["is_success"] == "True" for row in csv.DictReader(f)}


def gate_table(today: date) -> tuple[list[dict[str, Any]], bool]:
    stories = load_stories(today)
    runs = sorted(EVAL.glob("run*"))
    rows, ok = [], bool(runs)
    for name, story in stories.items():
        row: dict[str, Any] = {"story": name, "holdout": bool(story.get("x_holdout")), "runs": []}
        for run_dir in runs:
            summary = latest_summary(run_dir)
            judge_file = run_dir / "judge.json"
            evaluator = eval_success(summary).get(name, False) if summary else False
            db_errors = (
                json.loads(judge_file.read_text()).get(name, ["no judge"])
                if judge_file.exists()
                else ["no judge"]
            )
            row["runs"].append({"run": run_dir.name, "evaluator": evaluator, "db": db_errors})
            ok = ok and evaluator and not db_errors
        rows.append(row)
    return rows, ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["render", "reset", "judge", "gate", "cleanup"])
    parser.add_argument("--run", type=int, default=1)
    args = parser.parse_args()
    today = today_colombia()
    if args.command == "render":
        print(f"rendered stories for {today} in {render(args.run, today).relative_to(ROOT)}")
    elif args.command == "reset":
        deleted = asyncio.run(delete_travelers(PREFIX))
        seeded = seed_profiles(load_stories(today))
        print(f"deleted {deleted} golden traveler(s); seeded {seeded} profile(s)")
    elif args.command == "cleanup":
        print(f"deleted {asyncio.run(delete_travelers('test+'))} test traveler(s)")
    elif args.command == "judge":
        result = judge(args.run, today)
        for name, errors in result.items():
            print(
                f"  {'ok  ' if not errors else 'FAIL'} {name}"
                + "".join(f"\n       - {e}" for e in errors)
            )
    else:
        rows, ok = gate_table(today)
        EVAL.mkdir(parents=True, exist_ok=True)
        (EVAL / "gate.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        for row in rows:
            marks = " ".join(
                ("ok" if r["evaluator"] and not r["db"] else "FAIL") + f"({r['run']})"
                for r in row["runs"]
            )
            print(f"  {row['story']:<34} {'holdout ' if row['holdout'] else ''}{marks}")
        print("golden gate:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
