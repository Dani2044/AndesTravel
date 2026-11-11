"""Convert watsonx Orchestrate OpenAPI tool specs to and from a one-operation OpenAPI file.

Tools created from the Orchestrate UI have no uploaded OpenAPI artifact, so
`orchestrate tools export` skips them. The platform still stores the full tool
spec (input/output schema + HTTP binding), and the ADK builds that spec from an
OpenAPI operation in a deterministic way
(`ibm_watsonx_orchestrate.agent_builder.tools.openapi_tool.create_openapi_json_tool`).
`spec_to_openapi` is the inverse of that function, and `openapi_to_tool` runs the
ADK function itself, so a pulled file pushes back to the same tool spec.
"""

from __future__ import annotations

import copy
from typing import Any

# Keys the ADK writes onto every parameter schema; they live on the parameter itself.
_PARAM_KEYS = ("in", "aliasName", "title", "description")
_BODY = "__requestBody__"
_CONTENT_TYPE = "application/json"


def spec_to_openapi(tool: dict[str, Any]) -> dict[str, Any]:
    """Build a single-operation OpenAPI 3 document from a tool spec (`tools list -v`)."""
    binding = tool["binding"]["openapi"]
    input_schema = tool.get("input_schema") or {}
    required = set(input_schema.get("required") or [])

    operation: dict[str, Any] = {
        "operationId": tool["name"],
        "summary": tool.get("display_name") or tool["name"],
        "description": tool.get("description") or "",
    }
    if tool.get("permission") and tool["permission"] != "read_only":
        operation["x-ibm-orchestrate-permission"] = tool["permission"]

    parameters = []
    for key, prop in (input_schema.get("properties") or {}).items():
        prop = copy.deepcopy(prop)
        if key == _BODY or prop.get("in") == "body":
            prop.pop("in", None)
            operation["requestBody"] = {
                "required": key in required,
                "content": {_CONTENT_TYPE: {"schema": prop}},
            }
            continue
        param: dict[str, Any] = {
            "name": prop.get("aliasName") or key.split("_", 1)[-1],
            "in": prop["in"],
            "required": key in required,
        }
        if prop.get("description") is not None:
            param["description"] = prop["description"]
        param["schema"] = {k: v for k, v in prop.items() if k not in _PARAM_KEYS}
        parameters.append(param)
    if parameters:
        operation["parameters"] = parameters

    output = copy.deepcopy(tool.get("output_schema") or {})
    response: dict[str, Any] = {"description": output.pop("description", None) or "OK"}
    output.pop("required", None)
    if output:
        response["content"] = {_CONTENT_TYPE: {"schema": output}}
    operation["responses"] = {"200": response}

    doc: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {"title": tool.get("display_name") or tool["name"], "version": "1.0.0"},
        "servers": [{"url": s} for s in binding.get("servers") or []],
        "paths": {binding["http_path"]: {binding["http_method"].lower(): operation}},
    }

    security = binding.get("security") or []
    if security:
        schemes = {}
        for i, sec in enumerate(security):
            scheme = {k: v for k, v in sec.items() if v is not None}
            if "in_field" in scheme:
                scheme["in"] = scheme.pop("in_field")
            schemes[f"scheme{i}"] = scheme
        doc["components"] = {"securitySchemes": schemes}
        operation["security"] = [{name: []} for name in schemes]
    return doc


def operation_of(doc: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """Return (path, METHOD, operation) of a single-operation document."""
    ((path, methods),) = doc["paths"].items()
    ((method, op),) = methods.items()
    return path, method.upper(), op


def openapi_to_tool(doc: dict[str, Any], connection_id: str | None = None):
    """Build the ADK OpenAPITool for a single-operation document, keeping the exact name."""
    from ibm_watsonx_orchestrate.agent_builder.tools.openapi_tool import (
        create_openapi_json_tool,
    )
    from ibm_watsonx_orchestrate.agent_builder.tools.types import ToolPermission

    path, method, op = operation_of(doc)
    permission = op.get("x-ibm-orchestrate-permission", "read_only")
    tool = create_openapi_json_tool(
        openapi_spec=copy.deepcopy(doc),
        http_path=path,
        http_method=method,
        name=op["operationId"],
        display_name=op.get("summary"),
        description=op.get("description"),
        permission=ToolPermission(permission),
        connection_id=connection_id,
    )
    # The ADK always marks the request body as required; restore what the file says.
    body = op.get("requestBody")
    if body is not None and not body.get("required", True):
        req = tool.__tool_spec__.input_schema.required
        if _BODY in req:
            req.remove(_BODY)
    return tool


def dump_tool_spec(tool) -> dict[str, Any]:
    return tool.__tool_spec__.model_dump(
        mode="json", exclude_unset=True, exclude_none=True, by_alias=True
    )


_COMPARED = ("name", "display_name", "description", "permission", "input_schema", "output_schema")


def _norm(value: Any) -> Any:
    """Normalize for comparison: drop nulls, sort `required` lists."""
    if isinstance(value, dict):
        out = {k: _norm(v) for k, v in value.items() if v is not None}
        if isinstance(out.get("required"), list):
            out["required"] = sorted(out["required"])
        if out.get("required") == []:
            out.pop("required")
        if out.get("properties") == {}:
            out.pop("properties")
        return out
    if isinstance(value, list):
        return [_norm(v) for v in value]
    return value


def roundtrip_diff(remote: dict[str, Any]) -> list[str]:
    """Differences between a remote tool spec and the spec rebuilt from its OpenAPI file."""
    rebuilt = dump_tool_spec(
        openapi_to_tool(spec_to_openapi(remote), remote["binding"]["openapi"].get("connection_id"))
    )
    diffs = []
    for key in _COMPARED:
        if _norm(remote.get(key)) != _norm(rebuilt.get(key)):
            diffs.append(key)
    rb, lb = remote["binding"]["openapi"], rebuilt["binding"]["openapi"]
    for key in ("http_method", "http_path", "servers", "connection_id"):
        if _norm(rb.get(key)) != _norm(lb.get(key)):
            diffs.append(f"binding.{key}")
    if _norm(rb.get("security") or []) != _norm(lb.get("security") or []):
        diffs.append("binding.security")
    return diffs
