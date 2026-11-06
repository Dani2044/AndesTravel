"""Version a watsonx Orchestrate environment as files: pull, plan, push.

Run with the ADK's own interpreter (see orchestrate/README.md), for example:

    make wxo-pull     # instance -> files
    make wxo-plan     # what differs between the files and the instance
    make wxo-push     # dry run of what push would change
    make wxo-push APPLY=1

The active `orchestrate env` must point at the instance named in
orchestrate/environment.yaml; every command checks that first.
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from openapi_codec import openapi_to_tool, operation_of, spec_to_openapi  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "environment.yaml"
APP_ID_EXT = "x-ibm-orchestrate-app-id"

# Folders managed by pull, in push order (dependencies first).
KINDS = [
    "connections",
    "voice_configs",
    "toolkits",
    "knowledge_bases",
    "tools",
    "skills",
    "agents",
]
# Kinds whose remote state holds data the files do not (credentials, documents,
# MCP tool selection). Push only creates them when missing unless --update-safe.
SAFE_KINDS = {"connections", "voice_configs", "toolkits", "knowledge_bases"}


# --------------------------------------------------------------------------- helpers


def log(msg: str) -> None:
    print(msg, flush=True)


def orch(*args: str, timeout: int = 300) -> str:
    """Run the orchestrate CLI non-interactively and return stdout."""
    cmd = ["orchestrate", *args]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed:\n{proc.stdout[-2000:]}{proc.stderr[-2000:]}")
    return proc.stdout


def orch_json(*args: str):
    out = orch(*args)
    start = min(i for i in (out.find("["), out.find("{")) if i >= 0)
    return json.loads(out[start:], strict=False)


class _Dumper(yaml.SafeDumper):
    pass


def _str_repr(dumper: yaml.SafeDumper, value: str):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _str_repr)


def write_yaml(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)
    path.write_text(text, encoding="utf-8")


def read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def extract_zip(zip_path: Path, dest: Path, skip_prefixes: tuple[str, ...] = ()) -> list[Path]:
    """Extract a CLI export zip; its member names may start with '/' or '//'."""
    written = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename.lstrip("/")
            if not name or name.endswith("/") or name.startswith(skip_prefixes):
                continue
            target = (dest / name).resolve()
            if dest.resolve() not in target.parents:
                raise RuntimeError(f"unsafe path in {zip_path}: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))
            written.append(target)
    return written


def safe_name(name: str) -> str:
    return name.replace("/", "_").replace(":", "_")


# --------------------------------------------------------------------------- environment


def load_env() -> dict:
    return read_yaml(ENV_FILE)


def check_active_env() -> None:
    """Refuse to run against any instance other than the one in environment.yaml."""
    expected = load_env()
    out = orch("env", "list")
    active = [line for line in out.splitlines() if "(active)" in line]
    if not active or expected["name"] not in active[0].split():
        raise SystemExit(
            f"Active orchestrate env is not '{expected['name']}'.\n"
            f"Run: orchestrate env activate {expected['name']}\n"
            f"(env list says: {active[0].strip() if active else 'nothing active'})"
        )


# --------------------------------------------------------------------------- pull


@dataclass
class Snapshot:
    agents: list[dict] = field(default_factory=list)
    tools: dict[str, dict] = field(default_factory=dict)  # id -> spec
    toolkits: dict[str, dict] = field(default_factory=dict)  # id -> toolkit
    connections: dict[str, str] = field(default_factory=dict)  # connection_id -> app_id
    knowledge_bases: dict[str, dict] = field(default_factory=dict)  # id -> kb
    skills: list[dict] = field(default_factory=list)


def snapshot() -> Snapshot:
    snap = Snapshot()
    agents = orch_json("agents", "list", "-v")
    for kind in ("native", "external", "assistant"):
        for agent in agents.get(kind) or []:
            agent["_kind"] = kind
            snap.agents.append(agent)
    snap.tools = {t["id"]: t for t in orch_json("tools", "list", "-v")}
    snap.toolkits = {t["id"]: t for t in orch_json("toolkits", "list", "-v")}
    for conn in orch_json("connections", "list", "-v"):
        snap.connections[conn["connection_id"]] = conn["app_id"]
    snap.knowledge_bases = {k["id"]: k for k in orch_json("knowledge-bases", "list", "-v")}
    snap.skills = orch_json("skills", "list", "-v")
    return snap


def _tool_kind(spec: dict) -> str:
    return next(iter(spec.get("binding") or {}), "unknown")


def pull(dest: Path) -> dict:
    """Write the in-scope part of the remote environment under dest. Returns a summary.

    Scope comes from environment.yaml: `scope.agents` lists root agents (their
    collaborators are followed), and only what those agents use is pulled.
    """
    scope = load_env().get("scope") or {}
    snap = snapshot()
    by_name = {t["name"]: t for t in snap.tools.values()}
    agents_by_name = {a["name"]: a for a in snap.agents}
    for kind in KINDS:
        shutil.rmtree(dest / kind, ignore_errors=True)
    summary: dict[str, list[str]] = {k: [] for k in KINDS}
    warnings: list[str] = []
    app_ids: set[str] = set()
    toolkit_ids: set[str] = set()
    voice_configs: set[str] = set()
    kb_names: set[str] = set()
    skill_names: set[str] = set()
    tool_names: set[str] = set()

    # Agents: the roots in scope plus every collaborator they reach.
    queue = list(scope.get("agents") or agents_by_name)
    selected: set[str] = set()
    while queue:
        name = queue.pop(0)
        if name in selected:
            continue
        agent = agents_by_name.get(name)
        if agent is None:
            warnings.append(f"agent {name} (in scope) not found in the instance")
            continue
        selected.add(name)
        out = dest / "agents" / f"{safe_name(name)}.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        orch("agents", "export", "-n", name, "-k", agent["_kind"], "--agent-only", "-o", str(out))
        summary["agents"].append(name)
        data = read_yaml(out)
        queue.extend(data.get("collaborators") or [])
        tool_names.update(data.get("tools") or [])
        kb_names.update(data.get("knowledge_base") or [])
        skill_names.update(data.get("skills") or [])
        if data.get("voice_configuration"):
            voice_configs.add(data["voice_configuration"])
    summary["agents"].sort()
    if not scope.get("voice_configs", True):
        voice_configs.clear()

    # Skills (before tools: a skill's WXO.yaml lists tools by name that it calls).
    for skill in sorted(snap.skills, key=lambda s: s["name"]):
        if skill["name"] not in skill_names:
            continue
        out = dest / "skills" / safe_name(skill["name"])
        with tempfile.TemporaryDirectory() as tmp:
            orch("skills", "export", "-n", skill["name"], "-o", tmp)
            skill_md = next(Path(tmp).rglob("SKILL.md"))
            shutil.copytree(skill_md.parent, out)
        summary["skills"].append(skill["name"])
        wxo = out / "WXO.yaml"
        tool_names.update((read_yaml(wxo) or {}).get("tools") or [] if wxo.exists() else [])

    tool_ids = set()
    for ref in tool_names:
        spec = by_name.get(ref) or snap.tools.get(ref)
        if spec is None:
            warnings.append(f"unknown tool {ref} is referenced")
        else:
            tool_ids.add(spec["id"])

    # Tools.
    for tool_id in sorted(tool_ids, key=lambda i: snap.tools[i]["name"]):
        spec = snap.tools[tool_id]
        name, kind = spec["name"], _tool_kind(spec)
        if spec.get("toolkit_id"):
            toolkit_ids.add(spec["toolkit_id"])
            continue
        if kind == "openapi":
            doc = spec_to_openapi(spec)
            conn_id = spec["binding"]["openapi"].get("connection_id")
            if conn_id:
                app_id = snap.connections.get(conn_id)
                if app_id is None:
                    warnings.append(f"tool {name}: connection {conn_id} not found")
                else:
                    _, _, op = operation_of(doc)
                    op[APP_ID_EXT] = app_id
                    app_ids.add(app_id)
            write_yaml(dest / "tools" / "openapi" / f"{safe_name(name)}.yaml", doc)
        elif kind in ("python", "flow", "langflow"):
            tool_dir = dest / "tools" / kind / safe_name(name)
            with tempfile.TemporaryDirectory() as tmp:
                zpath = Path(tmp) / "tool.zip"
                orch("tools", "export", "-n", name, "-o", str(zpath))
                if not zpath.exists():
                    warnings.append(f"tool {name}: export produced no file, skipped")
                    continue
                extract_zip(zpath, tool_dir, skip_prefixes=("connections/",))
            binding = spec["binding"][kind]
            apps = sorted((binding.get("connections") or {}).keys())
            app_ids.update(apps)
            meta = {"name": name, "kind": kind, "app_ids": apps}
            if kind == "python":
                meta["function"] = binding.get("function")
            write_yaml(tool_dir / "tool.meta.yaml", meta)
        else:
            warnings.append(f"tool {name}: kind '{kind}' is not supported, skipped")
            continue
        summary["tools"].append(name)

    # Toolkits referenced by agent tools (MCP servers).
    for tk_id in sorted(toolkit_ids):
        tk = snap.toolkits.get(tk_id)
        if tk is None:
            warnings.append(f"toolkit {tk_id} not found")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            zpath = Path(tmp) / "tk.zip"
            orch("toolkits", "export", "-n", tk["name"], "-o", str(zpath))
            files = extract_zip(zpath, Path(tmp) / "x", skip_prefixes=("connections/",))
            spec_file = next(f for f in files if f.suffix in (".yaml", ".yml"))
            data = read_yaml(spec_file)
        data["connections"] = sorted(set(data.get("connections") or []))
        app_ids.update(data["connections"])
        write_yaml(dest / "toolkits" / f"{safe_name(tk['name'])}.yaml", data)
        summary["toolkits"].append(tk["name"])

    # Knowledge bases (configuration only; documents are not exportable).
    known_kbs = {k["name"] for k in snap.knowledge_bases.values()}
    for name in sorted(kb_names):
        if name not in known_kbs:
            warnings.append(f"unknown knowledge base {name} is referenced")
            continue
        out = dest / "knowledge_bases" / f"{safe_name(name)}.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        orch("knowledge-bases", "export", "-n", name, "-o", str(out))
        summary["knowledge_bases"].append(name)

    # Voice configurations referenced by agents (API keys are stripped by the CLI).
    for name in sorted(voice_configs):
        out = dest / "voice_configs" / f"{safe_name(name)}.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        orch("voice-configs", "export", "-n", name, "-o", str(out))
        summary["voice_configs"].append(name)

    # Connections (configuration only; credentials never leave the instance).
    for app_id in sorted(app_ids):
        out = dest / "connections" / f"{safe_name(app_id)}.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        orch("connections", "export", "-a", app_id, "-o", str(out))
        summary["connections"].append(app_id)

    return {"summary": summary, "warnings": warnings}


# --------------------------------------------------------------------------- plan


@dataclass
class Item:
    kind: str
    name: str
    path: Path  # file or directory under the repo (or staging)


def items(root: Path) -> dict[tuple[str, str], Item]:
    """Index the managed resources under root by (kind, name)."""
    found: dict[tuple[str, str], Item] = {}
    for kind in KINDS:
        base = root / kind
        if not base.exists():
            continue
        if kind == "tools":
            for f in sorted((base / "openapi").glob("*.yaml")):
                found[("tools", f.stem)] = Item("tools", f.stem, f)
            for sub in ("python", "flow", "langflow"):
                for d in sorted(p for p in (base / sub).glob("*") if p.is_dir()):
                    found[("tools", d.name)] = Item("tools", d.name, d)
        elif kind == "skills":
            for d in sorted(p for p in base.glob("*") if p.is_dir()):
                found[(kind, d.name)] = Item(kind, d.name, d)
        else:
            for f in sorted(base.glob("*.yaml")):
                found[(kind, f.stem)] = Item(kind, f.stem, f)
    return found


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
    for f in files:
        h.update(str(f.relative_to(path) if path.is_dir() else f.name).encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def same(a: Path, b: Path) -> bool:
    if a.is_file() and b.is_file():
        return filecmp.cmp(a, b, shallow=False)
    return _digest(a) == _digest(b)


def plan() -> tuple[list, list, list, dict]:
    """Compare repo files with a fresh pull. Returns (added, changed, remote_only, pull info)."""
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp)
        info = pull(staging)
        local, remote = items(ROOT), items(staging)
        added = [local[k] for k in local if k not in remote]
        changed = [
            local[k] for k in local if k in remote and not same(local[k].path, remote[k].path)
        ]
        remote_only = [remote[k] for k in remote if k not in local]
    return added, changed, remote_only, info


# --------------------------------------------------------------------------- push


def _agent_order(agent_items: Iterable[Item]) -> list[Item]:
    """Collaborators before the agents that call them."""
    pending = {i.name: i for i in agent_items}
    deps = {
        name: set(read_yaml(i.path).get("collaborators") or []) & set(pending)
        for name, i in pending.items()
    }
    ordered: list[Item] = []
    while pending:
        ready = sorted(n for n in pending if not (deps[n] & set(pending)))
        if not ready:  # cycle: push the rest as-is
            ready = sorted(pending)
        for n in ready:
            ordered.append(pending.pop(n))
    return ordered


def _connection_id(app_id: str) -> str:
    from ibm_watsonx_orchestrate.client.connections import get_connections_client

    conn = get_connections_client().get_draft_by_app_id(app_id=app_id)
    if conn is None:
        raise RuntimeError(f"connection '{app_id}' does not exist in the instance; push it first")
    return conn.connection_id


def push_openapi_tool(path: Path) -> None:
    from ibm_watsonx_orchestrate.cli.commands.tools.tools_controller import (
        ToolKind,
        ToolsController,
    )

    doc = read_yaml(path)
    _, _, op = operation_of(doc)
    app_id = op.get(APP_ID_EXT)
    tool = openapi_to_tool(doc, _connection_id(app_id) if app_id else None)
    ToolsController(tool_kind=ToolKind.openapi, file=str(path)).publish_or_update_tools([tool])


def push_commands(item: Item) -> list[list[str]]:
    """CLI invocations for one resource (OpenAPI tools are pushed through the ADK library)."""
    p = str(item.path)
    if item.kind == "connections":
        return [["connections", "import", "-f", p]]
    if item.kind == "voice_configs":
        return [["voice-configs", "import", "-f", p]]
    if item.kind == "knowledge_bases":
        return [["knowledge-bases", "import", "-f", p]]
    if item.kind == "toolkits":
        cmd = ["toolkits", "import", "-f", p]
        for app in read_yaml(item.path).get("connections") or []:
            cmd += ["-a", app]
        return [cmd]
    if item.kind == "skills":
        return [["skills", "import", "-d", p, "--upsert"]]
    if item.kind == "agents":
        return [["agents", "import", "-f", p]]
    if item.kind == "tools" and item.path.is_dir():
        meta = read_yaml(item.path / "tool.meta.yaml")
        if meta["kind"] != "python":
            raise RuntimeError(f"pushing {meta['kind']} tools is not implemented ({item.name})")
        module = meta["function"].split(":")[0]
        py_files = list(item.path.rglob("*.py"))
        cmd = ["tools", "import", "-k", "python", "-f", str(item.path / f"{module}.py")]
        if (item.path / "requirements.txt").exists():
            cmd += ["-r", str(item.path / "requirements.txt")]
        if len(py_files) > 1:
            cmd += ["-p", p]
        for app in meta.get("app_ids") or []:
            cmd += ["-a", app]
        return [cmd]
    return []  # OpenAPI tool


def describe(item: Item) -> str:
    return f"{item.kind}/{item.name}"


def push(apply: bool, only: list[str], update_safe: bool) -> int:
    added, changed, remote_only, info = plan()
    todo = [(i, "create") for i in added] + [(i, "update") for i in changed]
    if only:
        todo = [(i, a) for i, a in todo if any(describe(i).startswith(o) for o in only)]
    skipped = [
        (i, a) for i, a in todo if a == "update" and i.kind in SAFE_KINDS and not update_safe
    ]
    todo = [t for t in todo if t not in skipped]

    by_kind = {k: [t for t in todo if t[0].kind == k] for k in KINDS}
    agents = {i.name: (i, a) for i, a in by_kind["agents"]}
    by_kind["agents"] = [agents[i.name] for i in _agent_order(i for i, _ in agents.values())]
    ordered = [t for k in KINDS for t in by_kind[k]]

    for item, _ in skipped:
        log(f"  skip   {describe(item)} (exists; pass --update-safe to overwrite)")
    for item in remote_only:
        log(f"  remote-only {describe(item)} (not deleted; run pull to bring it into the repo)")
    if not ordered:
        log("Nothing to push: the files match the instance.")
        return 0

    log(f"{'Applying' if apply else 'Would apply'} {len(ordered)} change(s):")
    failures = 0
    for item, action in ordered:
        log(f"  {action:<6} {describe(item)}")
        if not apply:
            continue
        try:
            cmds = push_commands(item)
            if item.kind == "tools" and not cmds:
                push_openapi_tool(item.path)
            for cmd in cmds:
                orch(*cmd)
            if item.kind == "connections" and action == "create":
                log(
                    "         set its credentials: orchestrate connections set-credentials"
                    f" -a {item.name} --env draft|live ..."
                )
        except Exception as exc:  # keep going; report at the end
            failures += 1
            log(f"         FAILED: {exc}")
    if not apply:
        log("Dry run only. Re-run with --apply (make wxo-push APPLY=1) to change the instance.")
    return 1 if failures else 0


# --------------------------------------------------------------------------- cli


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("pull", "plan", "push"):
        sub.add_parser(name)
    sub.choices["push"].add_argument(
        "--apply", action="store_true", help="really change the instance"
    )
    sub.choices["push"].add_argument(
        "--only",
        nargs="*",
        default=[],
        help="limit to kind/name prefixes, e.g. agents/Untitled_Agent_1_5717pu",
    )
    sub.choices["push"].add_argument(
        "--update-safe",
        action="store_true",
        help="also overwrite existing connections, voice configs, toolkits and knowledge bases",
    )
    args = parser.parse_args()

    check_active_env()
    if args.cmd == "pull":
        info = pull(ROOT)
        for kind, names in info["summary"].items():
            log(f"{kind:<16} {len(names)}")
        for w in info["warnings"]:
            log(f"warning: {w}")
        return 0
    if args.cmd == "plan":
        added, changed, remote_only, info = plan()
        for label, group in (
            ("local only", added),
            ("changed", changed),
            ("remote only", remote_only),
        ):
            for item in group:
                log(f"  {label:<12} {describe(item)}")
        if not (added or changed or remote_only):
            log("In sync: the files match the instance.")
        return 0
    return push(args.apply, args.only, args.update_safe)


if __name__ == "__main__":
    sys.exit(main())
