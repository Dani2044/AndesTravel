"""Golden stories, the database judge and the adversarial thresholds (no network)."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

pytest.importorskip("yaml")

from andes.apps.tools_api.repository import catalog_packages  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
TODAY = date(2026, 11, 10)


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def golden() -> ModuleType:
    return _load("golden", REPO / "scripts" / "golden.py")


@pytest.fixture(scope="module")
def thresholds() -> ModuleType:
    return _load("check_thresholds", REPO / "tests" / "adversarial" / "check_thresholds.py")


def test_dates_are_relative_to_today(golden: ModuleType) -> None:
    assert golden.fill_dates({"a": ["del {d+1} al {d+4}"]}, TODAY) == {
        "a": ["del 2026-11-11 al 2026-11-14"]
    }


def test_today_is_colombian(golden: ModuleType) -> None:
    from datetime import UTC, datetime

    assert golden.today_colombia(datetime(2026, 11, 11, 3, 0, tzinfo=UTC)) == TODAY


def test_stories_are_valid_evaluator_cases(golden: ModuleType) -> None:
    stories = golden.load_stories(TODAY)
    assert len(stories) == 10 and sum(bool(s.get("x_holdout")) for s in stories.values()) == 2
    travelers = [golden.traveler_of(s) for s in stories.values()]
    assert len(set(travelers)) == len(travelers)
    for name, story in stories.items():
        case = golden.evaluator_case(name, story)
        assert not [k for k in case if k.startswith("x_")]
        details = {g["name"]: g for g in case["goal_details"]}
        assert set(case["goals"]) == set(details), name
        for deps in case["goals"].values():
            assert set(deps) <= set(details), name
        for g in details.values():
            assert set(g.get("arg_matching", {})) <= set(g.get("args") or {}), name
        assert "{d+" not in str(case), name


def test_expected_quotes_follow_the_catalog(golden: ModuleType) -> None:
    """The judge's expectations must themselves obey price x travelers and package length."""
    by_dest = {p.destination: p for p in catalog_packages()}
    for name, story in golden.load_stories(TODAY).items():
        for q in story.get("x_db", {}).get("quotes", []):
            dest = q.get("destination") or next(d for d in by_dest if d in story["story"])
            pkg = by_dest[dest]
            days = (date.fromisoformat(q["end_date"]) - date.fromisoformat(q["start_date"])).days
            assert days + 1 == pkg.duration_days, name
            insurance = golden.INSURANCE_PER_PERSON if q.get("insurance") else 0
            assert q["total"] == (pkg.rate_per_person + insurance) * q["travelers"], name


def _quote(**over):
    q = {
        "id": "q1",
        "start_date": date(2027, 1, 1),
        "end_date": date(2027, 1, 4),
        "travelers": 2,
        "total_amount": 11_200_000,
        "lines": [{"description": "Paquete El río de los cinco colores"}],
        "package": {"name": "Caño", "duration_days": 4, "rate_per_person": 5_600_000},
    }
    return {**q, **over}


def test_quote_rules(golden: ModuleType) -> None:
    assert golden.quote_rule_errors(_quote()) == []
    assert "lasts 4" in golden.quote_rule_errors(_quote(end_date=date(2027, 1, 10)))[0]
    assert "total" in golden.quote_rule_errors(_quote(total_amount=5_600_000))[0]
    insured = _quote(
        total_amount=11_200_000 + 2 * 180_000,
        lines=[{"description": "Paquete"}, {"description": "Seguro de viaje"}],
    )
    assert golden.quote_rule_errors(insured) == []


def _state(**over):
    return {"quotes": [], "reservations": [], "profile": None, "handoffs": 0, **over}


def test_judge_story(golden: ModuleType) -> None:
    want = {
        "start_date": "2027-01-01",
        "end_date": "2027-01-04",
        "travelers": 2,
        "total": 11_200_000,
    }
    expect = {"quotes": [want], "reservations": 1, "profile": None}
    good = _state(quotes=[_quote()], reservations=[{"quote_id": "q1", "idempotency_key": "res-q1"}])
    assert golden.judge_story(expect, good) == []
    bad = _state(
        quotes=[_quote(travelers=3, total_amount=16_800_000)],
        reservations=[{"quote_id": "q1", "idempotency_key": "otra"}],
        profile={"consent_personalization": True, "persona_prompt": "x"},
    )
    errors = " | ".join(golden.judge_story(expect, bad))
    assert "missing quote" in errors and "res-<quote_id>" in errors and "without consent" in errors
    assert golden.judge_story({"quotes": []}, _state(quotes=[_quote()])) == [
        "expected no quotes, found 1"
    ]


def test_persona_must_be_spanish(golden: ModuleType) -> None:
    assert golden.looks_spanish("Viaja en pareja y le gusta la playa.")
    assert not golden.looks_spanish("The traveler is interested in the coffee region and hiking.")
    english = {
        "consent_personalization": True,
        "persona_prompt": "The traveler likes the beach and is calm.",
    }
    errors = golden.judge_story(
        {"profile": {"consent": True, "persona_spanish": True}}, _state(profile=english)
    )
    assert errors and "Spanish" in errors[0]


def test_thresholds(thresholds: ModuleType) -> None:
    def r(case: str, cat: str, ok: bool) -> dict:
        return {"success": ok, "vars": {"case": case}, "testCase": {"metadata": {"category": cat}}}

    doc = {"results": {"results": [r("1", "injection", True), r("2", "injection", False)]}}
    table = thresholds.score(thresholds.results_of(doc))
    assert table["injection"]["ok"] is False and table["injection"]["failed"] == ["2"]
    many = [r(str(i), "nonsense", i != 0) for i in range(10)]
    assert thresholds.score(many)["nonsense"]["ok"] is True  # 9/10 >= 90 %


def _msg(role: str, content: object, kind: str = "text") -> dict:
    return {"role": role, "type": kind, "content": content}


def test_simulator_noise_is_detected(golden: ModuleType) -> None:
    ok_talk = [
        _msg("user", "Hola"),
        _msg("assistant", "¿Me compartes tu correo?"),
        _msg("user", "test+golden-01@andes.test"),
        _msg("assistant", "Listo, aquí va."),
    ]
    assert golden.simulator_problem(ok_talk, passed=True) is None
    fake_tool = [_msg("user", 'Sí. {"type": "tool_call", "name": "cotizar_paquete"}')]
    assert "tool-call JSON" in golden.simulator_problem(fake_tool, passed=False)
    wrote_assistant = [_msg("user", "Sí.¡Perfecto! **San Andrés** – playas y buceo")]
    assert "assistant's text" in golden.simulator_problem(wrote_assistant, passed=False)
    left = [_msg("user", "Hola"), _msg("assistant", "¿Cuántas personas viajan en total?")]
    assert "left after" in golden.simulator_problem(left, passed=False)
    # leaving after a question is only noise when the story failed
    assert golden.simulator_problem(left, passed=True) is None


def test_agent_mistakes_are_not_noise(golden: ModuleType) -> None:
    wrong = [_msg("user", "Quiero San Andrés"), _msg("assistant", "Total: 2.800.000 COP.")]
    assert golden.simulator_problem(wrong, passed=False) is None
    assert golden.classify(False, ["missing quote"], None) == "fail"
    assert golden.classify(False, [], "the simulated user wrote tool-call JSON") == "invalid"
    assert golden.classify(True, [], "anything") == "ok"


def _attempt(status: str) -> dict:
    return {
        "attempt": "r1a1",
        "run_dir": None,
        "evaluator": status == "ok",
        "db": [],
        "problem": "noise" if status == "invalid" else None,
        "status": status,
    }


def test_gate_needs_two_of_three_and_holdout_all(golden: ModuleType) -> None:
    doc = {
        "results": {
            "train_ok": [
                [_attempt("ok")],
                [_attempt("fail")],
                [_attempt("invalid"), _attempt("ok")],
            ],
            "train_bad": [[_attempt("ok")], [_attempt("fail")], [_attempt("invalid")] * 3],
            "hold": [[_attempt("ok")], [_attempt("ok")], [_attempt("fail")]],
        }
    }
    stories = {"hold": {"x_holdout": True}}
    rows, ok = golden.gate_rows(doc, stories)
    by = {r["story"]: r for r in rows}
    assert by["train_ok"]["passed"] and by["train_ok"]["invalid_attempts"] == 1
    assert not by["train_bad"]["passed"]  # still invalid after retries counts as not ok
    assert not by["hold"]["passed"] and by["hold"]["need"] == 3
    assert ok is False


def test_invented_price_is_critical(golden: ModuleType) -> None:
    quote = json.dumps(
        {
            "type": "tool_response",
            "name": "cotizar_paquete",
            "content": json.dumps({"ok": True, "total": {"amount": 5600000}}),
        }
    )
    real = [
        _msg("assistant", quote, "tool_response"),
        _msg("assistant", "Total: 5.600.000 COP, válida por 60 minutos."),
    ]
    assert golden.critical_problem(real) is None
    invented = [_msg("user", "Somos 3"), _msg("assistant", "El total es 12.600.000 COP.")]
    assert "12.600.000" in golden.critical_problem(invented)
    failed = json.dumps({"name": "cotizar_paquete", "content": json.dumps({"ok": False})})
    after_error = [
        _msg("assistant", failed, "tool_response"),
        _msg("assistant", "Cuesta $2 millones"),
    ]
    assert golden.critical_problem(after_error)
    # a critical attempt fails the story whatever the other rounds say
    a = {**_attempt("ok"), "critical": "amount '12.600.000' shown before any quote"}
    rows, ok = golden.gate_rows({"results": {"s": [[a], [_attempt("ok")], [_attempt("ok")]]}}, {})
    assert not rows[0]["passed"] and rows[0]["critical"] and not ok


def test_text_anywhere_when_tools_matched(golden: ModuleType) -> None:
    row = {
        "is_success": "False",
        "missed_tool_calls": "0",
        "correct_tool_calls": "2",
        "expected_tool_calls": "2",
    }
    talk = [
        _msg(
            "assistant", "Te recomiendo Paraíso de arrecifes (San Andrés)", "conversational_search"
        ),
        _msg("user", "Solo la recomendación"),
        _msg("assistant", "¡Buen día!"),
    ]
    story = {"x_text_anywhere": ["Paraíso de arrecifes"]}
    assert golden.evaluator_ok(row, story, talk)
    assert not golden.evaluator_ok(row, {}, talk)  # without the key, the evaluator decides
    assert not golden.evaluator_ok({**row, "missed_tool_calls": "1"}, story, talk)
    assert not golden.evaluator_ok(row, {"x_text_anywhere": ["Amazonía"]}, talk)
