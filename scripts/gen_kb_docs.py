"""Generate the catalog document of the `andes_catalog_kb` knowledge base.

The source of truth is `CATALOG` in src/andes/core/seed.py; this script renders it as
Spanish Markdown at orchestrate/knowledge_bases/docs/catalogo.md. The output is
deterministic, so re-running it on an unchanged catalog leaves the file byte-identical.

    python scripts/gen_kb_docs.py           # write the file
    python scripts/gen_kb_docs.py --check   # exit 1 if the file is out of date
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SEED_FILE = ROOT / "src" / "andes" / "core" / "seed.py"


def _load_seed() -> Any:
    """Load seed.py on its own: `andes.core` pulls in settings and pydantic, seed does not,
    so this script runs with any Python 3.9+ and no installed dependencies."""
    spec = importlib.util.spec_from_file_location("andes_seed", SEED_FILE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CATALOG: list[dict[str, Any]] = _load_seed().CATALOG
SeedPackage = dict[str, Any]

OUTPUT = ROOT / "orchestrate" / "knowledge_bases" / "docs" / "catalogo.md"

# Who each tag suits, in the order they are listed when a package has several.
AUDIENCE = {
    "familia": "familias con niños",
    "pareja": "parejas",
    "aventura": "viajeros que buscan aventura y actividad física",
    "ecoturismo": "amantes del ecoturismo",
    "naturaleza": "quienes quieren contacto con la naturaleza",
    "playa": "quienes buscan playa y descanso",
    "buceo": "aficionados al buceo y al snorkel",
    "senderismo": "caminantes y senderistas",
    "cultural": "viajeros interesados en cultura e historia",
    "cultura": "viajeros interesados en cultura e historia",
    "gastronomía": "amantes de la gastronomía local",
    "museos": "amantes de los museos",
    "ciudad": "quienes prefieren planes de ciudad",
}


def format_cop(amount: int) -> str:
    """5200000 -> '5.200.000' (Colombian thousands separator)."""
    return f"{amount:,}".replace(",", ".")


def audience(package: SeedPackage) -> str:
    seen: list[str] = []
    for tag in package["tags"]:
        label = AUDIENCE.get(tag)
        if label and label not in seen:
            seen.append(label)
    if not seen:
        return "Todo tipo de viajeros."
    text = seen[0] if len(seen) == 1 else ", ".join(seen[:-1]) + " y " + seen[-1]
    return text[0].upper() + text[1:] + "."


def render_package(package: SeedPackage) -> str:
    days = package["duration_days"]
    nights = days - 1
    return "\n".join(
        [
            f"## {package['destination']}: {package['name']}",
            "",
            f"- **Destino:** {package['destination']}, Colombia",
            f"- **Duración:** {days} días y {nights} noches",
            f"- **Qué incluye:** {package['description']}",
            f"- **Ideal para:** {audience(package)}",
            f"- **Tarifa base:** desde {format_cop(package['base_rate'])} COP por persona",
            f"- **Palabras clave:** {', '.join(package['tags'])}",
            f"- **Código del paquete:** {package['id']}",
            "",
        ]
    )


def render() -> str:
    header = [
        "<!-- Generado por scripts/gen_kb_docs.py desde CATALOG en src/andes/core/seed.py.",
        "     No editar a mano: cambia el catálogo y vuelve a correr el script. -->",
        "",
        "# Catálogo de paquetes de Andes Travel",
        "",
        f"Andes Travel ofrece {len(CATALOG)} paquetes turísticos nacionales por Colombia. "
        "Las tarifas son tarifas base por persona en pesos colombianos (COP); el valor final "
        "depende de las fechas, el número de viajeros y la disponibilidad, y se confirma "
        "en una cotización.",
        "",
        "Resumen de destinos:",
        "",
    ]
    summary = [
        f"- {p['destination']} ({p['duration_days']} días): desde "
        f"{format_cop(p['base_rate'])} COP por persona"
        for p in CATALOG
    ]
    body = [render_package(p) for p in CATALOG]
    return "\n".join([*header, *summary, ""]) + "\n" + "\n".join(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the file is out of date")
    args = parser.parse_args()
    text = render()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else None
        if current != text:
            print(f"{OUTPUT.relative_to(ROOT)} is out of date; run scripts/gen_kb_docs.py")
            return 1
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(text.encode("utf-8"))
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({len(CATALOG)} packages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
