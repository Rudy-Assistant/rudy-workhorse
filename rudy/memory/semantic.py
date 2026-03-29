"""
Semantic Memory — vector similarity search for the Oracle system.

Replaces ChromaDB with a zero-ops SQLite-backed solution.
Uses numpy for cosine similarity when sqlite-vec is not available,
with optional sqlite-vec acceleration for production.

Stores chunked text with embeddings for semantic retrieval:
  "What did the security scan find last week?"
  "Show me everything about network anomalies"

Embedding generation uses sentence-transformers (all-MiniLM-L6-v2)
for high-quality 384-dimensional vectors.

Migration path from knowledge_base.py:
  This module replaces ChromaDB with SQLite. The chunking and
  embedding logic is preserved. Collections map to the 'collection'
  column. The search API is compatible.
"""

import hashlib
import json
import logging
import re
import sqlite3
import struct
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from rudy.memory.schema import SEMANTIC_SCHEMA

log = logging.getLogger(__name__)

# Embedding model config
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384


def _file_hash(filepath: Path) -> str:
    """Quick hash of file for change detection."""
    h = hashlib.md5()
    h.update(str(filepath).encode())
    try:
        h.update(str(filepath.stat().st_mtime).encode())
        h.update(str(filepath.stat().st_size).encode())
    except OSError:
        h.update(b"missing")
    return h.hexdigest()[:16]


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """Split text into overlapping chunks for embedding.

    Uses sentence boundaries to avoid breaking mid-thought.
    """
    if not text or not text.strip():
        return []
    if len(text) <= chunk_size:
        return [text.strip()]

    chunks = []
    sentences = re.split(r"(?<=[.!?\n])\s+", text)
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) > chunk_size and current:
            chunks.append(current.strip())
            words = current.split()
            overlap_text = (
                " ".join(words[-overlap // 5 :]) if len(words) > overlap // 5 else ""
            )
            current = overlap_text + " " + sentence
        else:
            current += " " + sentence

    if current.strip():
        chunks.append(current.strip())
    return chunks


def _read_file(filepath: Path) -> str:
    """Read a file's content for indexing (max 10KB)."""
    try:
        if filepath.suffix == ".json":
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            return json.dumps(data, indent=2, default=str)[:10000]
        else:
            with open(filepath, encoding="utf-8", errors="replace") as f:
                return f.read()[:10000]
    except Exception as e:
        log.debug(f"Error reading {filepath}: {e}")
        return ""


def _serialize_vector(vec: List[float]) -> bytes:
    """Pack a float list into a compact binary blob."""
    return struct.pack(f"{len(vec)}f", *vec)


def _deserialize_vector(blob: bytes) -> List[float]:
    """Unpack a binary blob back to a float list."""
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors (pure Python fallback)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticMemory:
    """Vector similarity search backed by SQLite.

    Replaces the ChromaDB-based KnowledgeBase with a zero-ops solution.
    The database file, embedding generation, and search all run locally.

    Usage:
        sem = SemanticMemory(db_path)
        sem.add_text("Important security finding", source="sentinel")
        results = sem.search("security threats")
    """

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._embedder = None
        self._use_numpy = False
        self._init_db()
        self._try_numpy()

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with self._connect() as conn:
            conn.executescript(SEMANTIC_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        """Create a new connection."""
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _try_numpy(self) -> None:
        """Check if numpy is available for faster similarity."""
        try:
            import numpy  # noqa: F401

            self._use_numpy = True
        except ImportError:
            self._use_numpy = False

    def _get_embedder(self) -> Optional[object]:
        """Lazy-load the sentence transformer model."""
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._embedder = SentenceTransformer(EMBEDDING_MODEL)
            except ImportError:
                log.warning(
                    "sentence-transformers not installed. "
                    "Run: pip install sentence-transformers"
                )
                return None
        return self._embedder

    def _embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        embedder = self._get_embedder()
        if embedder is None:
            return []
        try:
            embeddings = embedder.encode(texts, show_progress_bar=False)
            return embeddings.tolist()
        except Exception as e:
            log.debug(f"Embedding generation failed: {e}")
            return []

    def _compute_similarities(
        self, query_vec: List[float], candidate_vecs: List[Tuple[int, bytes]]
    ) -> List[Tuple[int, float]]:
        """Compute cosine similarities, using numpy if available."""
        if self._use_numpy:
            import numpy as np

            q = np.array(query_vec, dtype=np.float32)
            q_norm = np.linalg.norm(q)
            if q_norm == 0:
                return [(cid, 0.0) for cid, _ in candidate_vecs]

            results = []
            for chunk_id, blob in candidate_vecs:
                c = np.frombuffer(blob, dtype=np.float32)
                c_norm = np.linalg.norm(c)
                if c_norm == 0:
                    results.append((chunk_id, 0.0))
                else:
                    sim = float(np.dot(q, c) / (q_norm * c_norm))
                    results.append((chunk_id, sim))
            return results
        else:
            results = []
            for chunk_id, blob in candidate_vecs:
                vec = _deserialize_vector(blob)
                sim = _cosine_similarity(query_vec, vec)
                results.append((chunk_id, sim))
            return results

    def add_text(
        self,
        text: str,
        collection: str = "general",
        source: str = "manual",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Add text to semantic memory.

        Text is chunked and embedded. Each chunk gets its own row.

        Args:
            text: The text content to store.
            collection: Category tag (e.g. "security", "research").
            source: Origin identifier.
            metadata: Optional extra metadata dict.

        Returns:
            Number of chunks stored.
        """
        if not text or not text.strip():
            return 0

        chunks = _chunk_text(text)
        if not chunks:
            return 0

        embeddings = self._embed(chunks)
        if not embeddings:
            log.warning("No embeddings generated — sentence-transformers may not be installed")
            return 0

        meta_json = json.dumps(metadata or {}, default=str)

        with self._connect() as conn:
            for i, (chunk, vec) in enumerate(zip(chunks, embeddings)):
                cursor = conn.execute(
                    """INSERT INTO chunks (text, source, collection, chunk_index, metadata)
                       VALUES (?, ?, ?, ?, ?)""",
                    (chunk, source, collection, i, meta_json),
                )
                chunk_id = cursor.lastrowid
                conn.execute(
                    "INSERT INTO embeddings (chunk_id, vector) VALUES (?, ?)",
                    (chunk_id, _serialize_vector(vec)),
                )

        return len(chunks)

    def index_file(
        self,
        filepath: Path,
        collection: str = "documents",
    ) -> Dict[str, Any]:
        """Index a single file into semantic memory.

        Skips files that haven't changed since last indexing.

        Returns:
            Dict with indexing results.
        """
        if not filepath.is_file():
            return {"error": f"Not a file: {filepath}", "chunks_added": 0}

        current_hash = _file_hash(filepath)

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM chunks WHERE file_path = ? AND file_hash = ?",
                (str(filepath), current_hash),
            ).fetchone()

        if existing:
            return {"status": "unchanged", "chunks_added": 0}

        # Remove old chunks for this file
        with self._connect() as conn:
            old_ids = conn.execute(
                "SELECT id FROM chunks WHERE file_path = ?",
                (str(filepath),),
            ).fetchall()
            for (old_id,) in old_ids:
                conn.execute("DELETE FROM embeddings WHERE chunk_id = ?", (old_id,))
            conn.execute("DELETE FROM chunks WHERE file_path = ?", (str(filepath),))

        content = _read_file(filepath)
        if not content.strip():
            return {"status": "empty", "chunks_added": 0}

        chunks = _chunk_text(content)
        embeddings = self._embed(chunks)
        if not embeddings:
            return {"status": "no_embeddings", "chunks_added": 0}

        with self._connect() as conn:
            for i, (chunk, vec) in enumerate(zip(chunks, embeddings)):
                cursor = conn.execute(
                    """INSERT INTO chunks
                       (text, source, collection, file_path, file_hash, chunk_index)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (chunk, filepath.name, collection, str(filepath), current_hash, i),
                )
                chunk_id = cursor.lastrowid
                conn.execute(
                    "INSERT INTO embeddings (chunk_id, vector) VALUES (?, ?)",
                    (chunk_id, _serialize_vector(vec)),
                )

        return {"status": "indexed", "chunks_added": len(chunks)}

    def search(
        self,
        query: str,
        collection: Optional[str] = None,
        n_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """Semantic search across stored knowledge.

        Args:
            query: Natural language search query.
            collection: Optional collection filter.
            n_results: Max results to return.

        Returns:
            List of result dicts with text, source, score, collection.
        """
        query_embedding = self._embed([query])
        if not query_embedding:
            return []
        query_vec = query_embedding[0]

        # Fetch candidate vectors
        with self._connect() as conn:
            if collection:
                rows = conn.execute(
                    """SELECT e.chunk_id, e.vector
                       FROM embeddings e
                       JOIN chunks c ON e.chunk_id = c.id
                       WHERE c.collection = ?""",
                    (collection,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT chunk_id, vector FROM embeddings"
                ).fetchall()

        if not rows:
            return []

        candidates = [(row[0], row[1]) for row in rows]
        similarities = self._compute_similarities(query_vec, candidates)

        # Sort by similarity, take top N
        similarities.sort(key=lambda x: x[1], reverse=True)
        top_ids = [s[0] for s in similarities[:n_results]]
        top_scores = {s[0]: s[1] for s in similarities[:n_results]}

        if not top_ids:
            return []

        # Fetch chunk details
        placeholders = ",".join("?" * len(top_ids))
        with self._connect() as conn:
            chunks = conn.execute(
                f"""SELECT id, text, source, collection, file_path, metadata
                    FROM chunks WHERE id IN ({placeholders})""",
                top_ids,
            ).fetchall()

        results = []
        for chunk in chunks:
            results.append({
                "text": chunk[1],
                "source": chunk[2],
                "collection": chunk[3],
                "filepath": chunk[4] or "",
                "score": round(top_scores.get(chunk[0], 0.0), 4),
                "metadata": json.loads(chunk[5]) if chunk[5] else {},
            })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    def delete_collection(self, collection: str) -> int:
        """Remove all chunks and embeddings for a collection."""
        with self._connect() as conn:
            chunk_ids = conn.execute(
                "SELECT id FROM chunks WHERE collection = ?", (collection,)
            ).fetchall()
            for (cid,) in chunk_ids:
                conn.execute("DELETE FROM embeddings WHERE chunk_id = ?", (cid,))
            deleted = conn.execute(
                "DELETE FROM chunks WHERE collection = ?", (collection,)
            ).rowcount
        return deleted

    def get_stats(self) -> Dict[str, Any]:
        """Get semantic memory statistics."""
        with self._connect() as conn:
            total_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            total_embeddings = conn.execute(
                "SELECT COUNT(*) FROM embeddings"
            ).fetchone()[0]
            collections = conn.execute(
                """SELECT collection, COUNT(*) as cnt
                   FROM chunks GROUP BY collection"""
            ).fetchall()

        return {
            "total_chunks": total_chunks,
            "total_embeddings": total_embeddings,
            "collections": {row[0]: row[1] for row in collections},
            "embedding_model": EMBEDDING_MODEL,
            "embedding_dim": EMBEDDING_DIM,
        }
