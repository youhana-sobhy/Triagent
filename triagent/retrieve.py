"""Retrieval over the runbooks (RAG).

Each runbook in data/runbooks/ is one short paragraph, so one runbook = one chunk.
Chroma embeds the chunks with its default local model (all-MiniLM-L6-v2) and
persists them to chroma_db/. If runbooks grow to several sections, split them
into smaller chunks in `index_runbooks`.
"""

import threading

import chromadb

from triagent import config

_lock = threading.Lock()
_collection = None


def _get_collection():
    global _collection
    with _lock:
        if _collection is None:
            client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
            _collection = client.get_or_create_collection(name="runbooks")
            if _collection.count() < len(runbook_ids()):
                index_runbooks(_collection)
    return _collection


def runbook_ids() -> list[str]:
    """Runbook IDs are the file names without .md, e.g. 'database-disk-full'."""
    return sorted(p.stem for p in config.RUNBOOKS_DIR.glob("*.md"))


def index_runbooks(collection=None, verbose: bool = False) -> int:
    """Embed every runbook into Chroma. Safe to rerun: upsert replaces existing IDs."""
    collection = collection or _get_collection()
    for path in sorted(config.RUNBOOKS_DIR.glob("*.md")):
        collection.upsert(
            ids=[path.stem],
            documents=[path.read_text(encoding="utf-8")],
            metadatas=[{"runbook": path.stem, "file": path.name}],
        )
        if verbose:
            print(f"indexed  {path.stem}")
    return collection.count()


def search(alert: str, k: int = config.TOP_K) -> list[tuple[str, float]]:
    """Embed the alert and return the k closest runbooks as (runbook_id, distance). Lower = closer."""
    if not alert.strip():
        return []
    result = _get_collection().query(query_texts=[alert], n_results=k)
    return list(zip(result["ids"][0], result["distances"][0]))


def get_runbook_text(runbook_id: str) -> str:
    path = config.RUNBOOKS_DIR / f"{runbook_id}.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def format_runbooks(runbook_ids_: list[str]) -> str:
    """Render retrieved runbooks for a prompt, each tagged with its ID."""
    if not runbook_ids_:
        return "(no runbooks retrieved)"
    return "\n".join(
        f'<runbook id="{rid}">\n{get_runbook_text(rid)}\n</runbook>' for rid in runbook_ids_
    )
