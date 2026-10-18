"""Command-line entrypoints.

python -m andes.cli migrate   # create the database schema
python -m andes.cli seed      # load the catalog into knowledge_chunks
"""

from __future__ import annotations

import argparse
import asyncio

from andes.core.config import get_settings
from andes.core.seed import CATALOG, SeedPackage
from andes.knowledge.embeddings import get_embedder
from andes.persistence import create_all, make_engine, make_sessionmaker
from andes.persistence.models import KnowledgeChunk


def _document(package: SeedPackage) -> str:
    return (
        f"{package['destination']} {package['name']}. {package['description']} "
        f"tags: {', '.join(package['tags'])}"
    )


async def _migrate() -> None:
    engine = make_engine()
    await create_all(engine)
    await engine.dispose()
    print("schema created")


async def _seed() -> None:
    engine = make_engine()
    await create_all(engine)
    sessionmaker = make_sessionmaker(engine)
    embedder = get_embedder()
    async with sessionmaker() as session:
        for package in CATALOG:
            session.add(
                KnowledgeChunk(
                    package_id=package["id"],
                    destination=package["destination"],
                    content=_document(package),
                    embedding=embedder(_document(package)),
                )
            )
        await session.commit()
    await engine.dispose()
    print(f"seeded {len(CATALOG)} knowledge chunks")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="andes")
    parser.add_argument("command", choices=["migrate", "seed", "info"])
    args = parser.parse_args(argv)

    if args.command == "migrate":
        asyncio.run(_migrate())
    elif args.command == "seed":
        asyncio.run(_seed())
    else:
        settings = get_settings()
        print(f"env={settings.app_env} llm={settings.llm_provider} db={settings.database_url}")


if __name__ == "__main__":
    main()
