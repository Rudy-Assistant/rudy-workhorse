"""Tests for rudy.memory.semantic — Semantic Memory (vector search).

These tests mock the sentence-transformers embedder to avoid
requiring the ML model during testing. The embedding logic is
tested with deterministic fake vectors.
"""

import json
import sqlite3
import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rudy.memory.semantic import (
    SemanticMemory,
    _chunk_text,
    _cosine_similarity,
    _file_hash,
    _read_file,
    _serialize_vector,
    _deserialize_vector,
)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_memory.sqlite"


def _fake_embed(texts):
    """Generate deterministic fake embeddings based on text content."""
    vecs = []
    for text in texts:
        # Create a simple hash-based vector (384 dims to match model)
        seed = sum(ord(c) for c in text)
        vec = [(seed + i) % 100 / 100.0 for i in range(384)]
        vecs.append(vec)
    return vecs


@pytest.fixture
def sem(db_path):
    """SemanticMemory with mocked embedder."""
    s = SemanticMemory(db_path)
    s._embed = _fake_embed
    return s


# ── Utility Functions ───────────────────────────────────────────


class TestChunkText:
    def test_short_text_single_chunk(self):
        assert _chunk_text("Hello world") == ["Hello world"]

    def test_empty_text(self):
        assert _chunk_text("") == []
        assert _chunk_text("   ") == []

    def test_long_text_multiple_chunks(self):
        text = ". ".join(f"Sentence number {i}" for i in range(50))
        chunks = _chunk_text(text, chunk_size=200)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 250  # Allow some overlap margin

    def test_preserves_content(self):
        text = "First sentence. Second sentence. Third sentence."
        chunks = _chunk_text(text, chunk_size=100)
        combined = " ".join(chunks)
        assert "First" in combined
        assert "Third" in combined

    def test_custom_chunk_size(self):
        text = "A. B. C. D. E. F. G. H. I. J."
        chunks_small = _chunk_text(text, chunk_size=10)
        chunks_large = _chunk_text(text, chunk_size=1000)
        assert len(chunks_small) > len(chunks_large)


class TestVectorSerialization:
    def test_roundtrip(self):
        vec = [0.1, 0.2, 0.3, 0.4, 0.5]
        blob = _serialize_vector(vec)
        result = _deserialize_vector(blob)
        for a, b in zip(vec, result):
            assert abs(a - b) < 1e-6

    def test_empty_vector(self):
        vec = []
        blob = _serialize_vector(vec)
        assert _deserialize_vector(blob) == []

    def test_large_vector(self):
        vec = [float(i) / 384 for i in range(384)]
        blob = _serialize_vector(vec)
        result = _deserialize_vector(blob)
        assert len(result) == 384


class TestCosineSimilarity:
    def test_identical_vectors(self):
        vec = [1.0, 2.0, 3.0]
        assert abs(_cosine_similarity(vec, vec) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert abs(_cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors(self):
        a = [1.0, 2.0, 3.0]
        b = [-1.0, -2.0, -3.0]
        assert abs(_cosine_similarity(a, b) - (-1.0)) < 1e-6

    def test_zero_vector(self):
        a = [0.0, 0.0, 0.0]
        b = [1.0, 2.0, 3.0]
        assert _cosine_similarity(a, b) == 0.0


class TestFileHash:
    def test_same_file_same_hash(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        assert _file_hash(f) == _file_hash(f)

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("hello")
        f2.write_text("world")
        assert _file_hash(f1) != _file_hash(f2)

    def test_missing_file(self, tmp_path):
        f = tmp_path / "missing.txt"
        h = _file_hash(f)  # Should not raise
        assert isinstance(h, str)


class TestReadFile:
    def test_read_text_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello world")
        assert _read_file(f) == "Hello world"

    def test_read_json_file(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text(json.dumps({"key": "value"}))
        content = _read_file(f)
        assert "key" in content

    def test_missing_file(self, tmp_path):
        f = tmp_path / "missing.txt"
        assert _read_file(f) == ""

    def test_truncation(self, tmp_path):
        f = tmp_path / "big.txt"
        f.write_text("x" * 20000)
        content = _read_file(f)
        assert len(content) <= 10000


# ── SemanticMemory ──────────────────────────────────────────────


class TestInit:
    def test_creates_db(self, db_path):
        sem = SemanticMemory(db_path)
        assert db_path.exists()

    def test_creates_tables(self, db_path):
        SemanticMemory(db_path)
        conn = sqlite3.connect(str(db_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = [t[0] for t in tables]
        assert "chunks" in names
        assert "embeddings" in names
        conn.close()


class TestAddText:
    def test_add_simple_text(self, sem):
        count = sem.add_text("This is a test document about security")
        assert count > 0

    def test_add_empty_text(self, sem):
        assert sem.add_text("") == 0
        assert sem.add_text("   ") == 0

    def test_add_with_collection(self, sem):
        sem.add_text("Security finding", collection="security")
        stats = sem.get_stats()
        assert "security" in stats["collections"]

    def test_add_with_metadata(self, sem):
        sem.add_text("Test", metadata={"author": "sentinel"})
        conn = sqlite3.connect(str(sem._db_path))
        row = conn.execute("SELECT metadata FROM chunks LIMIT 1").fetchone()
        meta = json.loads(row[0])
        assert meta["author"] == "sentinel"
        conn.close()

    def test_chunks_and_embeddings_match(self, sem):
        sem.add_text("A moderately long text. " * 50, collection="test")
        conn = sqlite3.connect(str(sem._db_path))
        chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        embeddings = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        assert chunks == embeddings
        conn.close()


class TestSearch:
    def test_basic_search(self, sem):
        sem.add_text("The network scanner found open port 8080", collection="security")
        sem.add_text("Today's weather is sunny and warm", collection="general")
        results = sem.search("network security ports")
        assert len(results) > 0

    def test_search_returns_scores(self, sem):
        sem.add_text("Test document")
        results = sem.search("test")
        assert all("score" in r for r in results)
        assert all(isinstance(r["score"], float) for r in results)

    def test_search_with_collection_filter(self, sem):
        sem.add_text("Security alert", collection="security")
        sem.add_text("Email draft", collection="email")
        results = sem.search("alert", collection="security")
        assert all(r["collection"] == "security" for r in results)

    def test_search_respects_n_results(self, sem):
        for i in range(10):
            sem.add_text(f"Document number {i}")
        results = sem.search("document", n_results=3)
        assert len(results) <= 3

    def test_search_empty_db(self, sem):
        results = sem.search("anything")
        assert results == []

    def test_search_result_structure(self, sem):
        sem.add_text("Test content", source="test_source", collection="test_col")
        results = sem.search("test")
        assert len(results) > 0
        r = results[0]
        assert "text" in r
        assert "source" in r
        assert "collection" in r
        assert "score" in r
        assert "filepath" in r


class TestIndexFile:
    def test_index_text_file(self, sem, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("Important security finding about the network")
        result = sem.index_file(f, collection="security")
        assert result["status"] == "indexed"
        assert result["chunks_added"] > 0

    def test_skip_unchanged_file(self, sem, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("Content")
        sem.index_file(f)
        result = sem.index_file(f)
        assert result["status"] == "unchanged"

    def test_reindex_changed_file(self, sem, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("Version 1")
        sem.index_file(f)
        f.write_text("Version 2 with different content")
        result = sem.index_file(f)
        assert result["status"] == "indexed"

    def test_index_missing_file(self, sem, tmp_path):
        f = tmp_path / "missing.txt"
        result = sem.index_file(f)
        assert "error" in result or result.get("status") == "empty"

    def test_index_empty_file(self, sem, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        result = sem.index_file(f)
        assert result["chunks_added"] == 0


class TestDeleteCollection:
    def test_delete_collection(self, sem):
        sem.add_text("Security data", collection="security")
        sem.add_text("Email data", collection="email")
        deleted = sem.delete_collection("security")
        assert deleted > 0
        stats = sem.get_stats()
        assert "security" not in stats["collections"]
        assert "email" in stats["collections"]

    def test_delete_nonexistent_collection(self, sem):
        deleted = sem.delete_collection("nonexistent")
        assert deleted == 0


class TestStats:
    def test_empty_stats(self, sem):
        stats = sem.get_stats()
        assert stats["total_chunks"] == 0
        assert stats["total_embeddings"] == 0
        assert stats["collections"] == {}

    def test_stats_after_indexing(self, sem):
        sem.add_text("Doc 1", collection="a")
        sem.add_text("Doc 2", collection="b")
        stats = sem.get_stats()
        assert stats["total_chunks"] >= 2
        assert len(stats["collections"]) == 2
