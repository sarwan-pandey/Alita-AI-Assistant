"""
ChromaDB Semantic Memory & RAG Module
=====================================
Provides vector storage and semantic retrieval for conversation context and document recall.
Gracefully handles environments where chromadb is optional or not installed.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("alita.chroma_rag")


class ChromaRAG:
    """Vector store wrapper around ChromaDB with fallback handling."""

    def __init__(self, collection_name: str = "alita_memories", persist_directory: Optional[str] = None):
        self.collection_name = collection_name
        self.persist_directory = persist_directory or "./data/chroma"
        self._client: Any = None
        self._collection: Any = None
        self._available = False
        self._init_chroma()

    def _init_chroma(self) -> None:
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            self._client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=ChromaSettings(anonymized_telemetry=False)
            )
            self._collection = self._client.get_or_create_collection(name=self.collection_name)
            self._available = True
            log.info("ChromaRAG initialized collection '%s' at %s", self.collection_name, self.persist_directory)
        except ImportError:
            log.info("chromadb not installed; ChromaRAG running in stub mode")
            self._available = False
        except Exception as exc:
            log.warning("ChromaRAG initialization warning: %s", exc)
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    def add_document(self, doc_id: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Add a text document with metadata to vector storage."""
        if not self._available or not self._collection:
            return False
        try:
            self._collection.upsert(
                documents=[text],
                ids=[doc_id],
                metadatas=[metadata or {}]
            )
            return True
        except Exception as exc:
            log.warning("ChromaRAG add_document failed for %s: %s", doc_id, exc)
            return False

    def query(self, query_text: str, n_results: int = 3, where: Optional[Dict[str, Any]] = None) -> List[str]:
        """Perform semantic similarity search and return relevant document texts."""
        if not self._available or not self._collection:
            return []
        try:
            kwargs: Dict[str, Any] = {
                "query_texts": [query_text],
                "n_results": n_results,
            }
            if where:
                kwargs["where"] = where
            results = self._collection.query(**kwargs)
            docs = results.get("documents", [[]])
            return docs[0] if docs else []
        except Exception as exc:
            log.warning("ChromaRAG query failed for '%s': %s", query_text[:40], exc)
            return []

    def delete_document(self, doc_id: str) -> bool:
        """Remove a document by ID."""
        if not self._available or not self._collection:
            return False
        try:
            self._collection.delete(ids=[doc_id])
            return True
        except Exception as exc:
            log.warning("ChromaRAG delete failed for %s: %s", doc_id, exc)
            return False
    def get_stats(self) -> Dict[str, Any]:
        """Return collection statistics."""
        count = 0
        if self._available and self._collection:
            try:
                count = self._collection.count()
            except Exception:
                pass
        return {
            "available": self._available,
            "collection": self.collection_name,
            "document_count": count,
        }


# Global default instance
chroma_rag = ChromaRAG()
