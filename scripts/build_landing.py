"""Build the landing page (build/web/index.html) from web/index.template.html.

The embedded chat needs the instance's orchestration id, CRN and the supervisor's live
environment id. They identify the IBM account, so they are not committed: this script
reads them from `orchestrate channels webchat embed` and writes the page to build/web/
(gitignored), which `make landing-deploy` publishes to Cloudflare Pages.

    uv run --env-file .env python scripts/build_landing.py --orchestrate <path to CLI>
    python scripts/build_landing.py --from-env    # Render static site build (no CLI there)

With --from-env the ids come from environment variables (set on the Render static site,
never in git): WXO_ORCHESTRATION_ID, WXO_HOST_URL, WXO_CRN, WXO_AGENT_ID,
WXO_AGENT_ENV_ID, plus TOOLS_API_URL. Standard library only, so any Python 3 builds it.
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "web" / "index.template.html"
OUT = ROOT / "build" / "web" / "index.html"
SUPERVISOR = "Untitled_Agent_1_5717pu"
FIELDS = {
    "ORCHESTRATION_ID": r'orchestrationID:\s*"([^"]+)"',
    "HOST_URL": r'hostURL:\s*"([^"]+)"',
    "CRN": r'crn:\s*"([^"]+)"',
    "AGENT_ID": r'agentId:\s*"([^"]+)"',
    "AGENT_ENV_ID": r'agentEnvironmentId:\s*"([^"]+)"',
}


def embed_values(snippet: str) -> dict[str, str]:
    """Pull the configuration values out of the CLI's embed snippet (it wraps long lines)."""
    flat = re.sub(r"\s*\n\s*", "", snippet)
    values = {}
    for name, pattern in FIELDS.items():
        match = re.search(pattern, flat)
        if not match:
            raise ValueError(f"{name} not found in the embed snippet")
        values[name] = match[1]
    return values


def destination_cards() -> str:
    spec = importlib.util.spec_from_file_location(
        "seed", ROOT / "src" / "andes" / "core" / "seed.py"
    )
    assert spec and spec.loader
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    cards = []
    for p in seed.CATALOG:  # no prices: the exact price only comes from a quote
        cards.append(
            '<div class="tile">'
            f'<div class="dest">{html.escape(p["destination"])}</div>'
            f'<div class="pkg">{html.escape(p["name"])}</div>'
            f'<div class="days">{p["duration_days"]} días</div>'
            "</div>"
        )
    return "\n      ".join(cards)


def instance_url() -> str:
    """The instance API URL (orchestrate/environment.yaml), e.g. .../instances/<id>."""
    text = (ROOT / "orchestrate" / "environment.yaml").read_text(encoding="utf-8")
    match = re.search(r"^url:\s*(\S+)", text, re.M)
    if not match:
        raise ValueError("url not found in orchestrate/environment.yaml")
    return match[1]


def render(template: str, values: dict[str, str]) -> str:
    out = template
    for name, value in values.items():
        out = out.replace("{{" + name + "}}", value)
    left = re.findall(r"\{\{[A-Z_]+\}\}", out)
    if left:
        raise ValueError(f"unfilled placeholders: {left}")
    return out


ENV_FIELDS = {
    "ORCHESTRATION_ID": "WXO_ORCHESTRATION_ID",
    "HOST_URL": "WXO_HOST_URL",
    "CRN": "WXO_CRN",
    "AGENT_ID": "WXO_AGENT_ID",
    "AGENT_ENV_ID": "WXO_AGENT_ENV_ID",
}


def env_values() -> dict[str, str]:
    missing = [env for env in ENV_FIELDS.values() if not os.environ.get(env)]
    if missing:
        sys.exit(f"missing environment variables: {', '.join(missing)}")
    return {name: os.environ[env] for name, env in ENV_FIELDS.items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--orchestrate", default="orchestrate")
    parser.add_argument("--from-env", action="store_true", help="ids from WXO_* variables")
    args = parser.parse_args()
    api = os.environ.get("TOOLS_API_URL", "").rstrip("/")
    if not api.startswith("https://"):
        sys.exit("TOOLS_API_URL must be the https URL of the tools API (put it in .env)")
    ids = env_values() if args.from_env else embed_values(cli_snippet(args.orchestrate))
    values = {
        **ids,
        "TOKEN_URL": f"{api}/webchat/token",
        "INSTANCE_URL": os.environ.get("WXO_INSTANCE_URL") or instance_url(),
        "DESTINATIONS": destination_cards(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(TEMPLATE.read_text(encoding="utf-8"), values), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


def cli_snippet(orchestrate: str) -> str:
    return subprocess.run(
        [
            orchestrate,
            "channels",
            "webchat",
            "embed",
            "--agent-name",
            SUPERVISOR,
            "--env",
            "live",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


if __name__ == "__main__":
    raise SystemExit(main())
