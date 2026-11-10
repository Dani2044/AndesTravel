"""Knowledge-base handling in orchestrate/scripts/wxo.py (pull keeps documents, push stages them).

wxo.py runs on the ADK interpreter; here it is loaded from its path and `orch` is
monkeypatched, so nothing touches the network or needs the ADK installed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
WXO_FILE = REPO / "orchestrate" / "scripts" / "wxo.py"


@pytest.fixture(scope="module")
def wxo():
    spec = importlib.util.spec_from_file_location("wxo_under_test", WXO_FILE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _kb(name: str, documents: list) -> dict:
    return {
        "spec_version": "v1",
        "kind": "knowledge_base",
        "name": name,
        "description": "kb",
        "documents": documents,
        "vector_index": {"embeddings_model_name": "ibm/granite-embedding-278m-multilingual"},
    }


# --------------------------------------------------------------------------- 4a: pull


def test_merge_kb_documents_puts_local_list_back(wxo):
    exported = _kb("andes_catalog_kb", [])
    merged = wxo.merge_kb_documents(exported, ["docs/catalogo.md"])
    assert merged["documents"] == ["docs/catalogo.md"]
    assert exported["documents"] == []  # input untouched
    assert list(merged) == list(exported)  # key order preserved


def test_merge_kb_documents_without_local_list_keeps_export(wxo):
    exported = _kb("x", [])
    assert wxo.merge_kb_documents(exported, None) is exported
    assert wxo.merge_kb_documents(exported, []) is exported


@pytest.fixture
def fake_instance(wxo, tmp_path, monkeypatch):
    """A repo at tmp_path/repo and an instance with one agent using two KBs."""
    root = tmp_path / "repo"
    kb_file = root / "knowledge_bases" / "andes_catalog_kb.yaml"
    _write(kb_file, _kb("andes_catalog_kb", ["docs/a.md"]))
    (root / "knowledge_bases" / "docs").mkdir(parents=True)
    (root / "knowledge_bases" / "docs" / "a.md").write_text("# a\n", encoding="utf-8")
    monkeypatch.setattr(wxo, "ROOT", root)
    monkeypatch.setattr(wxo, "load_env", lambda: {"scope": {"agents": ["sup"]}})
    snap = wxo.Snapshot(
        agents=[{"name": "sup", "_kind": "native"}],
        knowledge_bases={
            "1": {"id": "1", "name": "andes_catalog_kb"},
            "2": {"id": "2", "name": "old_kb"},
        },
    )
    monkeypatch.setattr(wxo, "snapshot", lambda: snap)
    calls: list[tuple[str, ...]] = []

    def fake_orch(*args: str, timeout: int = 300) -> str:
        calls.append(args)
        out = Path(args[args.index("-o") + 1])
        if args[:2] == ("agents", "export"):
            _write(out, {"name": "sup", "knowledge_base": ["andes_catalog_kb", "old_kb"]})
        elif args[:2] == ("knowledge-bases", "export"):
            name = args[args.index("-n") + 1]
            _write(out, {**_kb(name, []), "representation": "tool"})
        else:
            raise AssertionError(f"unexpected call {args}")
        return ""

    monkeypatch.setattr(wxo, "orch", fake_orch)
    return root, calls


def test_pull_keeps_local_documents_and_source_files(wxo, fake_instance):
    root, _ = fake_instance
    info = wxo.pull(root)
    assert info["summary"]["knowledge_bases"] == ["andes_catalog_kb", "old_kb"]
    kb = yaml.safe_load((root / "knowledge_bases" / "andes_catalog_kb.yaml").read_text())
    assert kb["documents"] == ["docs/a.md"]
    assert kb["representation"] == "tool"  # the rest comes from the export
    old = yaml.safe_load((root / "knowledge_bases" / "old_kb.yaml").read_text())
    assert old["documents"] == []  # no local list: export as-is
    assert (root / "knowledge_bases" / "docs" / "a.md").read_text() == "# a\n"


def test_pull_into_staging_uses_repo_documents(wxo, fake_instance, tmp_path):
    """`plan` pulls into a temp folder; it must compare against the same document list."""
    staging = tmp_path / "staging"
    wxo.pull(staging)
    kb = yaml.safe_load((staging / "knowledge_bases" / "andes_catalog_kb.yaml").read_text())
    assert kb["documents"] == ["docs/a.md"]


# --------------------------------------------------------------------------- 4b: push


@pytest.fixture
def kb_repo(tmp_path):
    kb_dir = tmp_path / "repo" / "knowledge_bases"
    (kb_dir / "docs").mkdir(parents=True)
    (kb_dir / "docs" / "catalogo.md").write_text("# Catálogo\n", encoding="utf-8")
    (kb_dir / "docs" / "notas.txt").write_text("notas\n", encoding="utf-8")
    documents = ["docs/catalogo.md", {"path": "docs/notas.txt", "url": "https://example.test/n"}]
    return _write(kb_dir / "andes_catalog_kb.yaml", _kb("andes_catalog_kb", documents))


def test_stage_resolves_documents_relative_to_yaml(wxo, kb_repo, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # cwd is not the YAML's folder
    staging = tmp_path / "staging"
    staged = wxo.stage_knowledge_base(kb_repo, staging)
    data = yaml.safe_load(staged.read_text(encoding="utf-8"))
    first, second = data["documents"]
    assert Path(first).is_absolute() and Path(first).name == "catalogo.txt"  # .md -> .txt
    assert Path(first).read_text(encoding="utf-8") == "# Catálogo\n"
    assert second["url"] == "https://example.test/n"
    assert Path(second["path"]).name == "notas.txt"
    assert data["vector_index"] == _kb("x", [])["vector_index"]
    assert yaml.safe_load(kb_repo.read_text())["documents"][0] == "docs/catalogo.md"  # untouched


def test_stage_missing_document_fails(wxo, kb_repo, tmp_path):
    (kb_repo.parent / "docs" / "catalogo.md").unlink()
    with pytest.raises(RuntimeError, match="docs/catalogo.md not found"):
        wxo.stage_knowledge_base(kb_repo, tmp_path / "staging")


def test_stage_duplicate_upload_name_fails(wxo, tmp_path):
    kb_dir = tmp_path / "kb"
    (kb_dir / "docs").mkdir(parents=True)
    for name in ("faq.md", "faq.txt"):
        (kb_dir / "docs" / name).write_text("x", encoding="utf-8")
    path = _write(kb_dir / "k.yaml", _kb("k", ["docs/faq.md", "docs/faq.txt"]))
    with pytest.raises(RuntimeError, match="faq.txt"):
        wxo.stage_knowledge_base(path, tmp_path / "staging")


def test_stage_without_documents_returns_original(wxo, tmp_path):
    path = _write(tmp_path / "k.yaml", _kb("k", []))
    assert wxo.stage_knowledge_base(path, tmp_path / "staging") == path.resolve()


def test_push_knowledge_base_imports_staged_copy(wxo, kb_repo, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seen: list[dict] = []

    def fake_orch(*args: str, timeout: int = 300) -> str:
        assert args[:3] == ("knowledge-bases", "import", "-f")
        data = yaml.safe_load(Path(args[3]).read_text(encoding="utf-8"))
        assert all(Path(wxo._doc_path(d)).is_file() for d in data["documents"])  # exist now
        seen.append(data)
        return ""

    monkeypatch.setattr(wxo, "orch", fake_orch)
    wxo.push_knowledge_base(kb_repo)
    assert len(seen) == 1
    assert [Path(wxo._doc_path(d)).name for d in seen[0]["documents"]] == [
        "catalogo.txt",
        "notas.txt",
    ]


def test_repo_kb_documents_exist(wxo, tmp_path):
    """The versioned andes_catalog_kb points at files that are really there."""
    kb = REPO / "orchestrate" / "knowledge_bases" / "andes_catalog_kb.yaml"
    staged = wxo.stage_knowledge_base(kb, tmp_path)
    names = [Path(d).name for d in yaml.safe_load(staged.read_text())["documents"]]
    assert names == ["catalogo.txt", "politicas_faq.txt"]
