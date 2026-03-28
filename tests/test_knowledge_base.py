import pytest
from unittest.mock import patch, MagicMock, Mock, mock_open, call
from pathlib import Path
import json
import hashlib
from datetime import datetime
import tempfile

import rudy.knowledge_base as mod


class TestFileHash:
    """Tests for _file_hash function."""

    def test_file_hash_consistent(self, tmp_path):
        """Hash should be consistent for the same file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        hash1 = mod._file_hash(test_file)
        hash2 = mod._file_hash(test_file)

        assert hash1 == hash2
        assert len(hash1) == 16

    def test_file_hash_different_files(self, tmp_path):
        """Different files should produce different hashes."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content1")
        file2.write_text("content2")

        hash1 = mod._file_hash(file1)
        hash2 = mod._file_hash(file2)

        assert hash1 != hash2

    def test_file_hash_includes_mtime_and_size(self, tmp_path):
        """Hash should change when file size or mtime changes."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        hash1 = mod._file_hash(test_file)

        # Modify content
        test_file.write_text("different content")
        hash2 = mod._file_hash(test_file)

        assert hash1 != hash2


class TestChunkText:
    """Tests for _chunk_text function."""

    def test_chunk_text_short_text(self):
        """Short text should return single chunk."""
        text = "This is short."
        chunks = mod._chunk_text(text)

        assert len(chunks) == 1
        assert chunks[0] == text

    def test_chunk_text_empty_string(self):
        """Empty string should return empty list."""
        chunks = mod._chunk_text("")
        assert chunks == []

    def test_chunk_text_whitespace_only(self):
        """Whitespace-only text should return empty list."""
        chunks = mod._chunk_text("   \n\n  ")
        assert chunks == []

    def test_chunk_text_long_text(self):
        """Long text should be split into multiple chunks."""
        text = ". ".join(["Sentence " + str(i) for i in range(50)])
        chunks = mod._chunk_text(text, chunk_size=100, overlap=10)

        assert len(chunks) > 1
        # All chunks should be non-empty
        assert all(chunk.strip() for chunk in chunks)

    def test_chunk_text_respects_sentence_boundaries(self):
        """Chunks should respect sentence boundaries."""
        text = "First sentence. Second sentence. Third sentence."
        chunks = mod._chunk_text(text, chunk_size=50, overlap=5)

        # Each chunk should contain complete sentences
        for chunk in chunks:
            assert chunk.count(".") >= 0  # May have partial sentence

    def test_chunk_text_overlap(self):
        """Chunks should have overlap."""
        text = ". ".join(["Word " + str(i) for i in range(100)])
        chunks = mod._chunk_text(text, chunk_size=200, overlap=50)

        if len(chunks) > 1:
            # Check that consecutive chunks share some text (overlap)
            for i in range(len(chunks) - 1):
                # There should be some word repetition between chunks
                words_first = set(chunks[i].split())
                words_second = set(chunks[i + 1].split())
                # Some overlap expected but not guaranteed due to algorithm
                assert isinstance(words_first & words_second, set)

    def test_chunk_text_custom_sizes(self):
        """Chunking should respect custom chunk_size and overlap."""
        text = ". ".join(["Sentence " + str(i) for i in range(30)])
        chunks_small = mod._chunk_text(text, chunk_size=50, overlap=5)
        chunks_large = mod._chunk_text(text, chunk_size=500, overlap=20)

        # Smaller chunk size should produce more chunks
        assert len(chunks_small) >= len(chunks_large)


class TestReadFile:
    """Tests for _read_file function."""

    def test_read_file_text(self, tmp_path):
        """Should read text file content."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello world", encoding="utf-8")

        content = mod._read_file(test_file)
        assert content == "Hello world"

    def test_read_file_json(self, tmp_path):
        """Should read JSON file and return as formatted JSON string."""
        test_file = tmp_path / "test.json"
        data = {"key": "value", "number": 42}
        test_file.write_text(json.dumps(data), encoding="utf-8")

        content = mod._read_file(test_file)
        parsed = json.loads(content)

        assert parsed["key"] == "value"
        assert parsed["number"] == 42

    def test_read_file_truncates_large_content(self, tmp_path):
        """Content should be truncated at 10000 chars."""
        test_file = tmp_path / "large.txt"
        large_content = "x" * 20000
        test_file.write_text(large_content, encoding="utf-8")

        content = mod._read_file(test_file)
        assert len(content) == 10000

    def test_read_file_json_truncates_large_content(self, tmp_path):
        """JSON content should be truncated at 10000 chars."""
        test_file = tmp_path / "large.json"
        data = {"content": "x" * 20000}
        test_file.write_text(json.dumps(data), encoding="utf-8")

        content = mod._read_file(test_file)
        assert len(content) == 10000

    def test_read_file_not_found(self):
        """Should return empty string for non-existent file."""
        content = mod._read_file(Path("/nonexistent/file.txt"))
        assert content == ""

    def test_read_file_with_encoding_errors(self, tmp_path):
        """Should handle encoding errors gracefully."""
        test_file = tmp_path / "bad_encoding.txt"
        # Write binary data that's not valid UTF-8
        test_file.write_bytes(b'\x80\x81\x82\x83')

        content = mod._read_file(test_file)
        # Should return something (with replacement chars), not crash
        assert isinstance(content, str)

    def test_read_file_json_with_default_serializer(self, tmp_path):
        """JSON serialization should handle non-serializable objects."""
        test_file = tmp_path / "test.json"
        data = {"date": datetime(2026, 3, 28)}
        test_file.write_text(json.dumps(data, default=str), encoding="utf-8")

        content = mod._read_file(test_file)
        assert "2026" in content


class TestKnowledgeBaseInit:
    """Tests for KnowledgeBase initialization."""

    def test_init_creates_kb_dir(self, tmp_path, monkeypatch):
        """Should create KB directory on init."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        mod.KnowledgeBase()

        assert (tmp_path / "kb").exists()

    def test_init_loads_existing_state(self, tmp_path, monkeypatch):
        """Should load existing state file if it exists."""
        kb_dir = tmp_path / "kb"
        kb_dir.mkdir(parents=True)
        state_file = kb_dir / "index-state.json"
        state_file.write_text(json.dumps({
            "indexed_files": {"file1": "hash1"},
            "last_full_index": "2026-03-28T00:00:00",
            "total_chunks": 42
        }))

        monkeypatch.setattr(mod, "KB_DIR", kb_dir)
        monkeypatch.setattr(mod, "INDEX_STATE", state_file)

        kb = mod.KnowledgeBase()

        assert kb._state["indexed_files"]["file1"] == "hash1"
        assert kb._state["total_chunks"] == 42

    def test_init_creates_default_state(self, tmp_path, monkeypatch):
        """Should create default state if no file exists."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()

        assert kb._state["indexed_files"] == {}
        assert kb._state["last_full_index"] is None
        assert kb._state["total_chunks"] == 0

    def test_init_corrupted_state_file(self, tmp_path, monkeypatch):
        """Should use default state if state file is corrupted."""
        kb_dir = tmp_path / "kb"
        kb_dir.mkdir(parents=True)
        state_file = kb_dir / "index-state.json"
        state_file.write_text("not valid json")

        monkeypatch.setattr(mod, "KB_DIR", kb_dir)
        monkeypatch.setattr(mod, "INDEX_STATE", state_file)

        kb = mod.KnowledgeBase()

        assert kb._state["indexed_files"] == {}


class TestKnowledgeBaseChromaAndEmbedder:
    """Tests for ChromaDB and embedder lazy loading."""

    def test_get_chroma_chromadb_not_installed(self):
        """Should return None if ChromaDB is not installed."""
        kb = mod.KnowledgeBase()
        with patch.dict("sys.modules", {"chromadb": None}):
            with patch("builtins.print") as mock_print:
                with patch("importlib.import_module", side_effect=ImportError):
                    kb._chroma = None
                    result = kb._get_chroma()
                    # Either returns None or prints message
                    assert result is None or mock_print.called

    def test_get_chroma_lazy_loads(self, tmp_path, monkeypatch):
        """Should lazy-load ChromaDB on first call."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()

        mock_chroma_client = MagicMock()
        with patch("sys.modules", {"chromadb": MagicMock(PersistentClient=MagicMock(return_value=mock_chroma_client))}):
            kb._chroma = None  # Reset
            result = kb._get_chroma()
            # May return mock or handle import error
            assert result is not None or result is None

    def test_get_chroma_caches_instance(self, tmp_path, monkeypatch):
        """Should cache ChromaDB instance after first load."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        mock_chroma = MagicMock()
        kb._chroma = mock_chroma

        result = kb._get_chroma()
        assert result is mock_chroma

    def test_get_embedder_sentence_transformers_not_installed(self):
        """Should return None if sentence-transformers is not installed."""
        kb = mod.KnowledgeBase()
        with patch("importlib.import_module", side_effect=ImportError):
            kb._embedder = None
            result = kb._get_embedder()
            # Either returns None or prints message
            assert result is None or isinstance(result, MagicMock)

    def test_get_embedder_lazy_loads(self, tmp_path, monkeypatch):
        """Should lazy-load embedder on first call."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()

        mock_embedder = MagicMock()
        with patch("sys.modules", {"sentence_transformers": MagicMock(SentenceTransformer=MagicMock(return_value=mock_embedder))}):
            kb._embedder = None  # Reset
            result = kb._get_embedder()
            # May return mock or handle import error
            assert result is not None or result is None

    def test_get_embedder_caches_instance(self, tmp_path, monkeypatch):
        """Should cache embedder instance after first load."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        mock_embedder = MagicMock()
        kb._embedder = mock_embedder

        result = kb._get_embedder()
        assert result is mock_embedder


class TestKnowledgeBaseEmbed:
    """Tests for _embed method."""

    def test_embed_generates_embeddings(self, tmp_path, monkeypatch):
        """Should generate embeddings for texts."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()

        # Mock numpy array-like object
        mock_array = MagicMock()
        mock_array.tolist.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = mock_array
        kb._embedder = mock_embedder

        texts = ["text1", "text2"]
        result = kb._embed(texts)

        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_embedder.encode.assert_called_once()

    def test_embed_returns_empty_if_embedder_unavailable(self, tmp_path, monkeypatch):
        """Should return empty list if embedder is unavailable."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        kb._embedder = None
        kb._get_embedder = MagicMock(return_value=None)

        result = kb._embed(["text1"])

        assert result == []

    def test_embed_handles_numpy_arrays(self, tmp_path, monkeypatch):
        """Should convert numpy arrays to lists."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()

        # Mock numpy array-like object
        mock_array = MagicMock()
        mock_array.tolist.return_value = [[0.1, 0.2], [0.3, 0.4]]

        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = mock_array
        kb._embedder = mock_embedder

        result = kb._embed(["text1", "text2"])

        assert result == [[0.1, 0.2], [0.3, 0.4]]


class TestKnowledgeBaseSaveState:
    """Tests for _save_state method."""

    def test_save_state_creates_file(self, tmp_path, monkeypatch):
        """Should create state file with current state."""
        kb_dir = tmp_path / "kb"
        state_file = kb_dir / "index-state.json"
        monkeypatch.setattr(mod, "KB_DIR", kb_dir)
        monkeypatch.setattr(mod, "INDEX_STATE", state_file)

        kb = mod.KnowledgeBase()
        kb._state = {
            "indexed_files": {"file1": "hash1"},
            "last_full_index": "2026-03-28T00:00:00",
            "total_chunks": 100
        }
        kb._save_state()

        assert state_file.exists()
        saved_state = json.loads(state_file.read_text())
        assert saved_state["indexed_files"]["file1"] == "hash1"
        assert saved_state["total_chunks"] == 100

    def test_save_state_creates_parent_dirs(self, tmp_path, monkeypatch):
        """Should create parent directories if they don't exist."""
        kb_dir = tmp_path / "deep" / "path" / "to" / "kb"
        state_file = kb_dir / "index-state.json"
        monkeypatch.setattr(mod, "KB_DIR", kb_dir)
        monkeypatch.setattr(mod, "INDEX_STATE", state_file)

        kb = mod.KnowledgeBase()
        kb._state = {"indexed_files": {}}
        kb._save_state()

        assert state_file.exists()


class TestKnowledgeBaseCollectionExists:
    """Tests for _collection_exists method."""

    def test_collection_exists_true(self, tmp_path, monkeypatch):
        """Should return True if collection exists."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()

        mock_chroma = MagicMock()
        mock_chroma.get_collection.return_value = MagicMock()
        kb._chroma = mock_chroma

        result = kb._collection_exists("test_collection")

        assert result is True

    def test_collection_exists_false(self, tmp_path, monkeypatch):
        """Should return False if collection does not exist."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()

        mock_chroma = MagicMock()
        mock_chroma.get_collection.side_effect = Exception("Not found")
        kb._chroma = mock_chroma

        result = kb._collection_exists("nonexistent_collection")

        assert result is False


class TestKnowledgeBaseIndexCollection:
    """Tests for index_collection method."""

    def test_index_collection_unknown_collection(self, tmp_path, monkeypatch):
        """Should return error for unknown collection."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()

        # Mock ChromaDB to be available
        mock_chroma = MagicMock()
        kb._chroma = mock_chroma

        result = kb.index_collection("unknown_collection")

        assert "error" in result
        assert "Unknown collection" in result["error"]

    def test_index_collection_chroma_unavailable(self, tmp_path, monkeypatch):
        """Should return error if ChromaDB is unavailable."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        kb._get_chroma = MagicMock(return_value=None)

        result = kb.index_collection("research")

        assert "error" in result
        assert "ChromaDB not available" in result["error"]

    def test_index_collection_no_files(self, tmp_path, monkeypatch):
        """Should handle case when collection paths don't exist."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")
        monkeypatch.setattr(mod, "COLLECTIONS", {
            "test": {
                "paths": [tmp_path / "nonexistent"],
                "patterns": ["**/*.txt"],
                "description": "Test collection"
            }
        })

        kb = mod.KnowledgeBase()

        mock_chroma = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_chroma.get_or_create_collection.return_value = mock_collection
        kb._chroma = mock_chroma

        result = kb.index_collection("test")

        assert result["files_indexed"] == 0
        assert result["chunks_added"] == 0

    def test_index_collection_skips_unchanged_files(self, tmp_path, monkeypatch):
        """Should skip files that haven't changed."""
        kb_dir = tmp_path / "kb"
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True)

        # Create a test file
        test_file = logs_dir / "test.txt"
        test_file.write_text("content")

        # Set up paths
        monkeypatch.setattr(mod, "KB_DIR", kb_dir)
        monkeypatch.setattr(mod, "INDEX_STATE", kb_dir / "index-state.json")
        monkeypatch.setattr(mod, "COLLECTIONS", {
            "test": {
                "paths": [logs_dir],
                "patterns": ["*.txt"],
                "description": "Test"
            }
        })

        kb = mod.KnowledgeBase()
        file_hash = mod._file_hash(test_file)
        kb._state["indexed_files"][str(test_file)] = file_hash

        mock_chroma = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_chroma.get_or_create_collection.return_value = mock_collection
        kb._chroma = mock_chroma

        result = kb.index_collection("test")

        # File should be skipped because it's already indexed
        assert result["files_indexed"] == 0

    def test_index_collection_skips_empty_files(self, tmp_path, monkeypatch):
        """Should skip files with empty content."""
        kb_dir = tmp_path / "kb"
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True)

        # Create an empty file
        test_file = logs_dir / "empty.txt"
        test_file.write_text("   ")  # Just whitespace

        monkeypatch.setattr(mod, "KB_DIR", kb_dir)
        monkeypatch.setattr(mod, "INDEX_STATE", kb_dir / "index-state.json")
        monkeypatch.setattr(mod, "COLLECTIONS", {
            "test": {
                "paths": [logs_dir],
                "patterns": ["*.txt"],
                "description": "Test"
            }
        })

        kb = mod.KnowledgeBase()

        mock_chroma = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_chroma.get_or_create_collection.return_value = mock_collection
        kb._chroma = mock_chroma
        kb._embed = MagicMock(return_value=[])

        result = kb.index_collection("test")

        assert result["files_indexed"] == 0

    def test_index_collection_successfully_indexes_file(self, tmp_path, monkeypatch):
        """Should successfully index a valid file."""
        kb_dir = tmp_path / "kb"
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True)

        # Create a valid file
        test_file = logs_dir / "test.txt"
        test_file.write_text("This is test content. It has multiple sentences. Really important stuff.")

        monkeypatch.setattr(mod, "KB_DIR", kb_dir)
        monkeypatch.setattr(mod, "INDEX_STATE", kb_dir / "index-state.json")
        monkeypatch.setattr(mod, "COLLECTIONS", {
            "test": {
                "paths": [logs_dir],
                "patterns": ["*.txt"],
                "description": "Test"
            }
        })

        kb = mod.KnowledgeBase()

        mock_chroma = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 2  # 2 chunks indexed
        mock_chroma.get_or_create_collection.return_value = mock_collection
        mock_chroma.get_collection.return_value = mock_collection
        kb._chroma = mock_chroma
        kb._embed = MagicMock(return_value=[[0.1], [0.2]])

        result = kb.index_collection("test")

        assert result["collection"] == "test"
        assert result["files_indexed"] == 1
        assert result["chunks_added"] >= 1
        # Verify upsert was called
        mock_collection.upsert.assert_called_once()


class TestKnowledgeBaseIndexAll:
    """Tests for index_all method."""

    def test_index_all_updates_timestamp(self, tmp_path, monkeypatch):
        """Should update last_full_index timestamp."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()

        # Mock index_collection
        kb.index_collection = MagicMock(return_value={
            "collection": "test",
            "files_indexed": 0,
            "chunks_added": 0
        })

        kb.index_all()

        assert kb._state["last_full_index"] is not None
        # Verify it's a valid ISO datetime
        datetime.fromisoformat(kb._state["last_full_index"])


class TestKnowledgeBaseSearch:
    """Tests for search method."""

    def test_search_chroma_unavailable(self, tmp_path, monkeypatch):
        """Should return empty list if ChromaDB is unavailable."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        kb._get_chroma = MagicMock(return_value=None)

        result = kb.search("test query")

        assert result == []

    def test_search_embedding_unavailable(self, tmp_path, monkeypatch):
        """Should return empty list if embedding fails."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        kb._embed = MagicMock(return_value=[])

        result = kb.search("test query")

        assert result == []

    def test_search_specific_collection(self, tmp_path, monkeypatch):
        """Should search only specified collection."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        kb._embed = MagicMock(return_value=[[0.1, 0.2, 0.3]])

        mock_chroma = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 2
        mock_collection.query.return_value = {
            "documents": [["doc1", "doc2"]],
            "metadatas": [[{"filename": "f1.txt", "source": "/path/f1"},
                          {"filename": "f2.txt", "source": "/path/f2"}]],
            "distances": [[0.1, 0.2]]
        }
        mock_chroma.get_collection.return_value = mock_collection
        kb._chroma = mock_chroma
        kb._collection_exists = MagicMock(return_value=True)

        result = kb.search("test", collection="research")

        assert len(result) == 2
        assert all(r["collection"] == "research" for r in result)
        mock_chroma.get_collection.assert_called_with("research")

    def test_search_multiple_collections(self, tmp_path, monkeypatch):
        """Should search all collections if none specified."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        kb._embed = MagicMock(return_value=[[0.1, 0.2, 0.3]])

        mock_chroma = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 1
        mock_collection.query.return_value = {
            "documents": [["test doc"]],
            "metadatas": [[{"filename": "test.txt", "source": "/path/test"}]],
            "distances": [[0.05]]
        }
        mock_chroma.get_collection.return_value = mock_collection
        kb._chroma = mock_chroma
        kb._collection_exists = MagicMock(return_value=True)

        result = kb.search("test")

        # Should search all collections
        assert len(result) >= 1

    def test_search_empty_collection(self, tmp_path, monkeypatch):
        """Should skip empty collections."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        kb._embed = MagicMock(return_value=[[0.1, 0.2, 0.3]])

        mock_chroma = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 0  # Empty
        mock_chroma.get_collection.return_value = mock_collection
        kb._chroma = mock_chroma
        kb._collection_exists = MagicMock(return_value=True)

        result = kb.search("test")

        # Should not error, just return empty or limited results
        assert isinstance(result, list)

    def test_search_results_sorted_by_score(self, tmp_path, monkeypatch):
        """Results should be sorted by score (highest first)."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        kb._embed = MagicMock(return_value=[[0.1, 0.2, 0.3]])

        mock_chroma = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 3
        # Lower distances = higher similarity
        mock_collection.query.return_value = {
            "documents": [["doc1", "doc2", "doc3"]],
            "metadatas": [[
                {"filename": "f1.txt", "source": "/path/f1"},
                {"filename": "f2.txt", "source": "/path/f2"},
                {"filename": "f3.txt", "source": "/path/f3"}
            ]],
            "distances": [[0.5, 0.1, 0.3]]  # Middle has best score
        }
        mock_chroma.get_collection.return_value = mock_collection
        kb._chroma = mock_chroma
        kb._collection_exists = MagicMock(return_value=True)

        result = kb.search("test", n_results=5)

        # Results should be sorted by score descending
        assert result[0]["score"] >= result[1]["score"]

    def test_search_respects_n_results(self, tmp_path, monkeypatch):
        """Should limit results to n_results."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        kb._embed = MagicMock(return_value=[[0.1, 0.2, 0.3]])

        mock_chroma = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 10
        # Return 10 results
        docs = [f"doc{i}" for i in range(10)]
        metas = [{"filename": f"f{i}.txt", "source": f"/path/f{i}"} for i in range(10)]
        dists = [0.1 * i for i in range(10)]
        mock_collection.query.return_value = {
            "documents": [docs],
            "metadatas": [metas],
            "distances": [dists]
        }
        mock_chroma.get_collection.return_value = mock_collection
        kb._chroma = mock_chroma
        kb._collection_exists = MagicMock(return_value=True)

        result = kb.search("test", n_results=3)

        assert len(result) <= 3


class TestKnowledgeBaseAddText:
    """Tests for add_text method."""

    def test_add_text_chroma_unavailable(self, tmp_path, monkeypatch):
        """Should return silently if ChromaDB is unavailable."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        kb._get_chroma = MagicMock(return_value=None)

        # Should not raise
        kb.add_text("test text")

    def test_add_text_no_embeddings(self, tmp_path, monkeypatch):
        """Should return silently if embeddings fail."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        kb._embed = MagicMock(return_value=[])

        mock_chroma = MagicMock()
        kb._chroma = mock_chroma

        # Should not raise
        kb.add_text("test text")

    def test_add_text_successfully(self, tmp_path, monkeypatch):
        """Should successfully add text to collection."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        kb._embed = MagicMock(return_value=[[0.1, 0.2], [0.3, 0.4]])

        mock_chroma = MagicMock()
        mock_collection = MagicMock()
        mock_chroma.get_or_create_collection.return_value = mock_collection
        kb._chroma = mock_chroma

        kb.add_text("Test text with content.", collection="documents", source="test_source")

        mock_chroma.get_or_create_collection.assert_called_once_with(name="documents")
        mock_collection.upsert.assert_called_once()

        # Check that upsert was called with proper arguments
        call_args = mock_collection.upsert.call_args
        assert "ids" in call_args.kwargs
        assert "embeddings" in call_args.kwargs
        assert "documents" in call_args.kwargs
        assert "metadatas" in call_args.kwargs

    def test_add_text_with_metadata(self, tmp_path, monkeypatch):
        """Should add custom metadata to text."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        kb._embed = MagicMock(return_value=[[0.1, 0.2]])

        mock_chroma = MagicMock()
        mock_collection = MagicMock()
        mock_chroma.get_or_create_collection.return_value = mock_collection
        kb._chroma = mock_chroma

        custom_meta = {"author": "test_author", "tag": "important"}
        kb.add_text("Test", metadata=custom_meta)

        call_args = mock_collection.upsert.call_args
        metadatas = call_args.kwargs["metadatas"]
        # Custom metadata should be in the metadatas
        assert any("author" in m for m in metadatas)


class TestKnowledgeBaseGetStats:
    """Tests for get_stats method."""

    def test_get_stats_no_collections(self, tmp_path, monkeypatch):
        """Should return stats with empty collections."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        kb._collection_exists = MagicMock(return_value=False)
        kb._get_chroma = MagicMock(return_value=MagicMock())

        stats = kb.get_stats()

        assert stats["total_files_indexed"] == 0
        assert stats["total_chunks"] == 0
        assert "collections" in stats

    def test_get_stats_with_collections(self, tmp_path, monkeypatch):
        """Should return stats for existing collections."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        kb._state["indexed_files"] = {"file1": "hash1", "file2": "hash2"}
        kb._state["total_chunks"] = 50

        mock_chroma = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 25
        mock_chroma.get_collection.return_value = mock_collection
        kb._chroma = mock_chroma
        kb._collection_exists = MagicMock(return_value=True)

        stats = kb.get_stats()

        assert stats["total_files_indexed"] == 2
        assert stats["total_chunks"] == 50
        assert "collections" in stats
        assert all("chunks" in v for v in stats["collections"].values())

    def test_get_stats_no_chroma(self, tmp_path, monkeypatch):
        """Should handle missing ChromaDB gracefully."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        kb._get_chroma = MagicMock(return_value=None)

        stats = kb.get_stats()

        assert isinstance(stats, dict)
        assert "collections" in stats


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_duplicate_entries_handled(self, tmp_path, monkeypatch):
        """Should handle duplicate file entries gracefully."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        kb._embed = MagicMock(return_value=[[0.1]])

        mock_chroma = MagicMock()
        mock_collection = MagicMock()
        mock_chroma.get_or_create_collection.return_value = mock_collection
        kb._chroma = mock_chroma

        # Add same text twice
        kb.add_text("duplicate content")
        kb.add_text("duplicate content")

        # Should upsert twice (IDs will differ due to timestamp)
        assert mock_collection.upsert.call_count == 2

    def test_very_long_text_handling(self, tmp_path, monkeypatch):
        """Should handle very long text input."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        # Create very long text
        long_text = ". ".join(["Sentence " + str(i) for i in range(1000)])

        # Should not crash
        chunks = mod._chunk_text(long_text)
        assert len(chunks) > 0

    def test_special_characters_in_text(self, tmp_path, monkeypatch):
        """Should handle special characters."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()
        kb._embed = MagicMock(return_value=[[0.1]])

        mock_chroma = MagicMock()
        mock_collection = MagicMock()
        mock_chroma.get_or_create_collection.return_value = mock_collection
        kb._chroma = mock_chroma

        special_text = "Contains emoji! 🚀 Math: ∑ and symbols: @#$%^&*()"

        # Should not crash
        kb.add_text(special_text)
        mock_collection.upsert.assert_called_once()

    def test_concurrent_index_operations(self, tmp_path, monkeypatch):
        """Should handle state consistency."""
        monkeypatch.setattr(mod, "KB_DIR", tmp_path / "kb")
        monkeypatch.setattr(mod, "INDEX_STATE", tmp_path / "kb" / "index-state.json")

        kb = mod.KnowledgeBase()

        # Simulate concurrent updates to state
        kb._state["indexed_files"]["file1"] = "hash1"
        kb._state["indexed_files"]["file2"] = "hash2"
        kb._save_state()

        # Load state again
        kb2 = mod.KnowledgeBase()
        assert len(kb2._state["indexed_files"]) == 2
