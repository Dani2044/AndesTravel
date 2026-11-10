"""scripts/gen_tool_specs.py turns the tools API into one OpenAPI file per Orchestrate tool."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
URL = "https://api.example.test"
EXPECTED = {
    "get_traveler_context": ("get", "/travelers/{traveler_id}/context"),
    "upsert_traveler_profile": ("put", "/travelers/{traveler_id}/profile"),
    "escalate_to_human": ("post", "/handoffs"),
    "check_availability": ("get", "/availability"),
    "quote_package": ("post", "/quotes"),
    "create_reservation": ("post", "/reservations"),
}


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location(
        "gen_tool_specs", REPO / "scripts" / "gen_tool_specs.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture(scope="module")
def docs(gen):
    from andes.apps.tools_api.main import create_app

    return gen.build_docs(create_app(api_key="x").openapi(), URL)


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_one_document_per_tool(docs):
    assert set(docs) == set(EXPECTED)
    for op_id, (method, path) in EXPECTED.items():
        doc = docs[op_id]
        assert doc["servers"] == [{"url": URL}]
        assert list(doc["paths"]) == [path]
        assert list(doc["paths"][path]) == [method]


def test_operations_carry_auth_and_connection(docs, gen):
    for doc in docs.values():
        ((_, methods),) = doc["paths"].items()
        ((method, op),) = methods.items()
        assert op[gen.APP_ID_EXT] == "andes_tools_api"
        assert op["security"] == [{"api_key": []}]
        scheme = doc["components"]["securitySchemes"]["api_key"]
        assert scheme == {"type": "apiKey", "in": "header", "name": "X-API-Key"}
        writes = method in gen.WRITE_METHODS
        assert (op.get("x-ibm-orchestrate-permission") == "read_write") is writes
        assert op["description"], "the description becomes the tool description for the LLM"


def test_schemas_are_self_contained(docs):
    for doc in docs.values():
        for node in _walk(doc):
            assert "$ref" not in node
            assert not any(v.get("type") == "null" for v in node.get("anyOf") or [])


def test_combined_document_holds_every_operation(docs, gen):
    doc = gen.combined(docs)
    ops = {op["operationId"] for methods in doc["paths"].values() for op in methods.values()}
    assert ops == set(EXPECTED)
    assert doc["servers"] == [{"url": URL}]
    assert "api_key" in doc["components"]["securitySchemes"]
