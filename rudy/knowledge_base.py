"""
Knowledge Base Engine — Semantic search over all Rudy data.

Uses ChromaDB for vector storage and sentence-transformers for embeddings.
Indexes: logs, research digests, briefings, documents, scan results,
agent reports, and any other text data the system produces.

Capabilities:
  - Semantic search: "What did the security scan find last week?"
  - Auto-indexing: New files are detected and indexed automatically
  - Collections: Organized by type (logs, research, security, personal)
  - Incremental: Only indexes new/changed content
  - Query context: Returns relevant chunks with source attribution
"""

import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List

from rudy.paths import BATCAVE_VAULT, RUDY_LOGS, RUDY_DATA, DESKTOP  # noqa: E402

LOGS = RUDY_LOGS
KB_DIR = RUDY_DATA / "knowledge-base"
INDEX_STATE = KB_DIR / "index-state.json"

# Collections and their source directories
COLLECTIONS = {
    "security": {
        "paths": [LOGS],
        "patterns": ["**/intruder-*.json", "**/network-defense-*.json",
                     "**/security-*.json", "**/threat-*.json"],
        "description": "Security scans, threat assessments, network defense results",
    },
    "research": {
        "paths": [LOGS],
        "patterns": ["**/research-digest-*.md", "**/research-*.json"],
        "description": "Daily research digests, AI/legal/tech news",
    },
    "agents": {
        "paths": [LOGS],
        "patterns": ["**/*-status.json", "**/agent-*.json",
                     "**/healthcheck*.json"],
        "description": "Agent status reports, health checks",
    },
    "briefings": {
        "paths": [DESKTOP / "briefings", DESKTOP / "audit-reports"],
        "patterns": ["**/*.md", "**/*.txt", "**/*.json"],
        "description": "Morning briefings, audit reports",
    },
    "documents": {
        "paths": [DESKTOP / "docs"],
        "patterns": ["**/*.md", "**/*.txt"],
        "description": "Documentation, guides, references",
    },
    "memory": {
        "paths": [DESKTOP / "memory"],
        "patterns": ["**/*.md", "**/*.json", "**/*.yaml"],
        "description": "Knowledge base files, people, projects",
    },
    "vault": {
        "paths": [BATCAVE_VAULT],
        "patterns": ["**/*.md"],
        "description": "BatcaveVault — mission, standing orders, session history, "
                       "architecture decisions, sprint logs, trackers, protocols",
    },
}

def _file_hash(filepath: Path) -> str:
    """Quick hash of file for change detection."""
    h = hashlib.md5(usedforsecurity=False)  # nosec B324
    h.update(str(filepath).encode())
    h.update(str(filepath.stat().st_mtime).encode())
    h.update(str(filepath.stat().st_size).encode())
    return h.hexdigest()[:16]

def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """Split text into overlapping chunks for embedding."""
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    chunks = []
    sentences = re.split(r'(?<=[.!?\n])\s+', text)
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) > chunk_size and current:
            chunks.append(current.strip())
            # Keep overlap from end of current chunk
            words = current.split()
            overlap_text = " ".join(words[-overlap//5:]) if len(words) > overlap//5 else ""
            current = overlap_text + " " + sentence
        else:
            current += " " + sentence

    if current.strip():
        chunks.append(current.strip())

    return chunks

def _read_file(filepath: Path) -> str:
    """Read a file's content for indexing."""
    try:
        if filepath.suffix == ".json":
            with open(filepath) as f:
                data = json.load(f)
            return json.dumps(data, indent=2, default=str)[:10000]
        else:
            with open(filepath, encoding="utf-8", errors="replace") as f:
                return f.read()[:10000]
    except Exception:
        return ""

class KnowledgeBase:
    """
    Semantic search engine for all Rudy data.

    Usage:
        kb = KnowledgeBase()
        kb.index_all()  # Index everything
        results = kb.search("network security threats this week")
        for r in results:
            print(f"  [{r['score']:.2f}] {r['source']}: {r['text'][:100]}")
    """

    def __init__(self):
        KB_DIR.mkdir(parents=True, exist_ok=True)
        self._chroma = None
        self._embedder = None
        self._state = self._load_state()

    def _load_state(self) -> dict:
        if INDEX_STATE.exists():
            try:
                with open(INDEX_STATE) as f:
                    return json.load(f)
            except Exception:
                pass
        return {"indexed_files": {}, "last_full_index": None, "total_chunks": 0}

    def _save_state(self):
        INDEX_STATE.parent.mkdir(parents=True, exist_ok=True)
        with open(INDEX_STATE, "w") as f:
            json.dump(self._state, f, indent=2, default=str)

    def _get_chroma(self):
        """Lazy-load ChromaDB client."""
        if self._chroma is None:
            try:
                import chromadb
                self._chroma = chromadb.PersistentClient(path=str(KB_DIR / "chromadb"))
            except ImportError:
                print("ChromaDB not installed. Run: pip install chromadb")
                return None
        return self._chroma

    def _get_embedder(self):
        """Lazy-load sentence transformer."""
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer
                # all-MiniLM-L6-v2: fast, good quality, 384 dimensions
                self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
            except ImportError:
                print("sentence-transformers not installed. Run: pip install sentence-transformers")
                return None
        return self._embedder

    def _embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        embedder = self._get_embedder()
        if embedder is None:
            return []
        embeddings = embedder.encode(texts, show_progress_bar=False)
        return embeddings.tolist()

    def index_collection(self, collection_name: str) -> dict:
        """Index or re-index a specific collection."""
        chroma = self._get_chroma()
        if chroma is None:
            return {"error": "ChromaDB not available"}

        config = COLLECTIONS.get(collection_name)
        if not config:
            return {"error": f"Unknown collection: {collection_name}"}

        collection = chroma.get_or_create_collection(
            name=collection_name,
            metadata={"description": config["description"]},
        )

        files_indexed = 0
        chunks_added = 0

        for base_path in config["paths"]:
            if not base_path.exists():
                continue

            for pattern in config["patterns"]:
                for filepath in base_path.glob(pattern):
                    if not filepath.is_file():
                        continue

                    file_hash = _file_hash(filepath)
                    if self._state["indexed_files"].get(str(filepath)) == file_hash:
                        continue  # Already indexed, unchanged

                    content = _read_file(filepath)
                    if not content.strip():
                        continue

                    chunks = _chunk_text(content)
                    if not chunks:
                        continue

                    # Generate embeddings
                    embeddings = self._embed(chunks)
                    if not embeddings:
                        continue

                    # Add to collection
                    ids = [f"{collection_name}_{filepath.stem}_{i}" for i in range(len(chunks))]
                    metadatas = [{
                        "source": str(filepath),
                        "filename": filepath.name,
                        "collection": collection_name,
                        "chunk_index": i,
                        "indexed_at": datetime.now().isoformat(),
                    } for i in range(len(chunks))]

                    # Upsert (handles re-indexing)
                    collection.upsert(
                        ids=ids,
                        embeddings=embeddings,
                        documents=chunks,
                        metadatas=metadatas,
                    )

                    self._state["indexed_files"][str(filepath)] = file_hash
                    files_indexed += 1
                    chunks_added += len(chunks)

        self._state["total_chunks"] = sum(
            chroma.get_collection(c).count()
            for c in [col for col in COLLECTIONS if self._collection_exists(col)]
        )
        self._save_state()

        return {
            "collection": collection_name,
            "files_indexed": files_indexed,
            "chunks_added": chunks_added,
        }

    def _collection_exists(self, name: str) -> bool:
        try:
            self._get_chroma().get_collection(name)
            return True
        except Exception:
            return False

    def index_all(self) -> dict:
        """Index all collections."""
        results = {}
        for name in COLLECTIONS:
            results[name] = self.index_collection(name)
        self._state["last_full_index"] = datetime.now().isoformat()
        self._save_state()
        return results

    def search(self, query: str, collection: str = None,
               n_results: int = 5) -> List[dict]:
        """
        Semantic search across the knowledge base.

        Returns list of results with score, text, and source.
        """
        chroma = self._get_chroma()
        if chroma is None:
            return []

        query_embedding = self._embed([query])
        if not query_embedding:
            return []

        results = []
        collections_to_search = [collection] if collection else list(COLLECTIONS.keys())

        for col_name in collections_to_search:
            if not self._collection_exists(col_name):
                continue

            col = chroma.get_collection(col_name)
            if col.count() == 0:
                continue

            hits = col.query(
                query_embeddings=query_embedding,
                n_results=min(n_results, col.count()),
            )

            for i, (doc, meta, dist) in enumerate(zip(
                hits["documents"][0],
                hits["metadatas"][0],
                hits["distances"][0],
            )):
                results.append({
                    "text": doc,
                    "source": meta.get("filename", "unknown"),
                    "collection": col_name,
                    "score": round(1 - dist, 4),  # Convert distance to similarity
                    "filepath": meta.get("source", ""),
                })

        # Sort by score, return top N
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:n_results]

    def add_text(self, text: str, collection: str = "documents",
                 source: str = "manual", metadata: dict = None):
        """Manually add text to the knowledge base."""
        chroma = self._get_chroma()
        if chroma is None:
            return

        col = chroma.get_or_create_collection(name=collection)
        chunks = _chunk_text(text)
        embeddings = self._embed(chunks)

        if not embeddings:
            return

        ids = [f"manual_{source}_{int(time.time())}_{i}" for i in range(len(chunks))]
        metadatas = [{
            "source": source,
            "collection": collection,
            "indexed_at": datetime.now().isoformat(),
            **(metadata or {}),
        } for _ in range(len(chunks))]

        col.upsert(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)

    def get_stats(self) -> dict:
        """Get knowledge base statistics."""
        chroma = self._get_chroma()
        collections_info = {}

        if chroma:
            for name in COLLECTIONS:
                if self._collection_exists(name):
                    col = chroma.get_collection(name)
                    collections_info[name] = {"chunks": col.count()}
                else:
                    collections_info[name] = {"chunks": 0}

        return {
            "total_files_indexed": len(self._state.get("indexed_files", {})),
            "total_chunks": self._state.get("total_chunks", 0),
            "last_full_index": self._state.get("last_full_index"),
            "collections": collections_info,
        }

if __name__ == "__main__":
    kb = KnowledgeBase()
    print("Knowledge Base Engine")
    print(json.dumps(kb.get_stats(), indent=2))
    print("\nIndexing all collections...")
    results = kb.index_all()
    print(json.dumps(results, indent=2))
    print("\nPost-index stats:")
    print(json.dumps(kb.get_stats(), indent=2))
