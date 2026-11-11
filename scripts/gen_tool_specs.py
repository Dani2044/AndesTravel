"""Generate the OpenAPI file to import the tools API (FastAPI) into watsonx Orchestrate.

Writes build/andes_tools_api.openapi.yaml (gitignored): every route as one operation,
schemas inlined, X-API-Key as the security scheme. Import it from the Orchestrate
console (Active inventory > Tools > Create tool > OpenAPI) bound to the
`andes_tools_api` connection; then `make wxo-pull` versions the tools the console
created under orchestrate/tools/openapi/ (named after each summary, e.g.
Cotizar_paquete_9624WG).

Run: TOOLS_API_URL=https://... uv run python scripts/gen_tool_specs.py  (make tools-specs)
"""

from __future__ import annotations

import copy
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from andes.apps.tools_api.main import create_app

ROOT = Path(__file__).resolve().parent.parent
UI_FILE = ROOT / "build" / "andes_tools_api.openapi.yaml"  # gitignored; for the Orchestrate UI
PLUGIN_FILE = ROOT / "build" / "price_guard.openapi.yaml"  # gitignored; orchestrate tools import
PLUGIN_EXT = "x-ibm-orchestrate-plugin"
APP_ID = "andes_tools_api"
APP_ID_EXT = "x-ibm-orchestrate-app-id"
HEADER = "X-API-Key"
WRITE_METHODS = {"post", "put", "patch", "delete"}


def _resolve(node: Any, components: dict[str, Any]) -> Any:
    """Inline $refs and turn `anyOf: [X, null]` (OpenAPI 3.1) into X."""
    if isinstance(node, list):
        return [_resolve(n, components) for n in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        merged = {
            **copy.deepcopy(components[name]),
            **{k: v for k, v in node.items() if k != "$ref"},
        }
        return _resolve(merged, components)
    out = {k: _resolve(v, components) for k, v in node.items()}
    variants = out.get("anyOf")
    if isinstance(variants, list):
        non_null = [v for v in variants if v.get("type") != "null"]
        if len(non_null) == 1 and len(non_null) < len(variants):
            out.pop("anyOf")
            out = {**non_null[0], **out}
    return out


def build_docs(
    spec: dict[str, Any], server_url: str, plugins: bool = False
) -> dict[str, dict[str, Any]]:
    """One document per tool; with plugins=True, one per plug-in (operations that carry
    x-ibm-orchestrate-plugin, which are imported apart and attached to an agent hook)."""
    components = spec.get("components", {}).get("schemas", {})
    docs: dict[str, dict[str, Any]] = {}
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            if (PLUGIN_EXT in op) != plugins:
                continue
            op_id = op["operationId"]
            operation: dict[str, Any] = {
                "operationId": op_id,
                "summary": op.get("summary") or op_id,
                "description": op.get("description") or "",
            }
            if method in WRITE_METHODS:
                operation["x-ibm-orchestrate-permission"] = "read_write"
            if op.get("parameters"):
                operation["parameters"] = _resolve(op["parameters"], components)
            if op.get("requestBody"):
                operation["requestBody"] = _resolve(op["requestBody"], components)
            ok = op["responses"]["200"]
            operation["responses"] = {"200": _resolve(ok, components)}
            if PLUGIN_EXT in op:
                operation[PLUGIN_EXT] = op[PLUGIN_EXT]
            operation["security"] = [{"api_key": []}]
            operation[APP_ID_EXT] = APP_ID
            docs[op_id] = {
                "openapi": "3.0.3",
                "info": {"title": operation["summary"], "version": spec["info"]["version"]},
                "servers": [{"url": server_url}],
                "paths": {path: {method: operation}},
                "components": {
                    "securitySchemes": {
                        "api_key": {"type": "apiKey", "in": "header", "name": HEADER}
                    }
                },
            }
    return docs


def combined(docs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """All operations in one document, for importing the tools from the Orchestrate UI."""
    first = next(iter(docs.values()))
    paths: dict[str, dict[str, Any]] = {}
    for doc in docs.values():
        for path, methods in doc["paths"].items():
            paths.setdefault(path, {}).update(methods)
    return {
        "openapi": first["openapi"],
        "info": {"title": "Andes Travel tools API", "version": first["info"]["version"]},
        "servers": first["servers"],
        "paths": paths,
        "components": first["components"],
    }


def _dump(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100))


def main() -> int:
    server_url = os.environ.get("TOOLS_API_URL", "").rstrip("/")
    if not server_url.startswith("https://"):
        sys.exit("TOOLS_API_URL must be the public https URL of the deployed tools API")
    spec = create_app(api_key="unused").openapi()
    docs = build_docs(spec, server_url)
    _dump(UI_FILE, combined(docs))
    print(f"wrote {len(docs)} operations to {UI_FILE.relative_to(ROOT)} (import it in the console)")
    plugin = build_docs(spec, server_url, plugins=True)["price_guard"]
    _dump(PLUGIN_FILE, plugin)
    print(f"wrote the price_guard plug-in to {PLUGIN_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
