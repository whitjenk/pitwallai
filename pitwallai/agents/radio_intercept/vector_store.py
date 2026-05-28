"""In-memory ChromaDB vector store for historical F1 radio transcripts."""

from __future__ import annotations

import asyncio
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection
from loguru import logger

from pitwallai.agents.radio_intercept.embedding import EmbeddingCache, get_embedding_model
from pitwallai.agents.radio_intercept.enums import RadioIntent, StrategicSignal
from pitwallai.agents.radio_intercept.models import HistoricalRadio
from pitwallai.agents.radio_intercept import seed_data

_REQUIRED_DOCUMENT_FIELDS = frozenset(
    {
        "doc_id",
        "raw_transcript",
        "decoded_intent",
        "strategic_signal",
        "session_type",
        "lap_number",
        "outcome",
        "team",
        "driver_code",
    }
)


class MockVectorStore:
    """
    In-memory vector store backed by ChromaDB and sentence-transformers embeddings.

    Provides semantic search over historical F1 team radio transcripts for
    grounding live decode operations.
    """

    def __init__(
        self,
        collection_name: str = "f1_radio_history",
        embedding_model: str = "all-MiniLM-L6-v2",
        embedding_cache_size: int = 512,
    ) -> None:
        """
        Initialize the mock vector store and seed historical transcripts.

        Args:
            collection_name: ChromaDB collection name.
            embedding_model: Sentence-transformers model identifier.
            embedding_cache_size: LRU cache size for query embeddings.
        """
        self._collection_name = collection_name
        self._embedding_model_name = embedding_model
        self._embedding_cache = EmbeddingCache(max_size=embedding_cache_size)
        self._client = chromadb.Client()
        self._embedding_model = get_embedding_model(embedding_model)
        self._collection: Collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self._seed()

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for a batch of texts synchronously.

        Uses an LRU cache for single-text queries (hot path in decode).

        Args:
            texts: Transcript strings to embed.

        Returns:
            List of embedding vectors.
        """
        if len(texts) == 1:
            key = texts[0]
            cached = self._embedding_cache.get(key)
            if cached is not None:
                return [cached]
            vector = self._embedding_model.encode([key], convert_to_numpy=True)[0].tolist()
            self._embedding_cache.put(key, vector)
            return [vector]

        embeddings = self._embedding_model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()

    def _seed(self) -> None:
        """
        Insert seed documents into the collection idempotently.

        Skips documents whose IDs already exist in the collection.
        """
        existing_ids: set[str] = set()
        if self._collection.count() > 0:
            existing = self._collection.get(include=[])
            existing_ids = set(existing.get("ids", []))

        to_insert: list[dict[str, Any]] = [
            record for record in seed_data.SEED_TRANSCRIPTS if record["doc_id"] not in existing_ids
        ]
        if not to_insert:
            logger.bind(collection=self._collection_name).info(
                "Vector store seed skipped — collection already populated"
            )
            return

        ids = [record["doc_id"] for record in to_insert]
        documents = [record["raw_transcript"] for record in to_insert]
        embeddings = self._embed(documents)
        metadatas = [self._record_to_metadata(record) for record in to_insert]

        self._collection.add(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        logger.bind(collection=self._collection_name, count=len(ids)).info(
            "Seeded historical radio transcripts"
        )

    @staticmethod
    def _record_to_metadata(record: dict[str, Any]) -> dict[str, str | int | float | bool]:
        """
        Convert a seed or runtime record dict to ChromaDB-compatible metadata.

        Args:
            record: Source document record.

        Returns:
            Metadata dict with scalar values only.
        """
        lap_number = record.get("lap_number")
        outcome = record.get("outcome")
        return {
            "decoded_intent": str(record["decoded_intent"]),
            "strategic_signal": str(record["strategic_signal"]),
            "session_type": str(record["session_type"]),
            "lap_number": int(lap_number) if lap_number is not None else -1,
            "outcome": str(outcome) if outcome is not None else "",
            "team": str(record["team"]),
            "driver_code": str(record["driver_code"]),
        }

    @staticmethod
    def _metadata_to_historical(
        doc_id: str,
        raw_transcript: str,
        metadata: dict[str, Any],
        similarity_score: float,
    ) -> HistoricalRadio:
        """
        Build a HistoricalRadio model from ChromaDB query result fields.

        Args:
            doc_id: Document identifier.
            raw_transcript: Stored transcript text.
            metadata: ChromaDB metadata dict.
            similarity_score: Converted similarity from distance.

        Returns:
            Populated HistoricalRadio instance.
        """
        lap_raw = metadata.get("lap_number", -1)
        lap_number = int(lap_raw) if int(lap_raw) >= 0 else None
        outcome_raw = metadata.get("outcome", "")
        outcome = str(outcome_raw) if outcome_raw else None

        return HistoricalRadio(
            doc_id=doc_id,
            raw_transcript=raw_transcript,
            decoded_intent=RadioIntent(str(metadata["decoded_intent"])),
            strategic_signal=StrategicSignal(str(metadata["strategic_signal"])),
            session_type=str(metadata["session_type"]),
            lap_number=lap_number,
            outcome=outcome,
            similarity_score=similarity_score,
        )

    def query(self, transcript: str, n_results: int = 5) -> list[HistoricalRadio]:
        """
        Perform semantic similarity search over historical transcripts.

        Args:
            transcript: Query transcript text.
            n_results: Maximum number of results to return.

        Returns:
            Ranked list of HistoricalRadio records with similarity scores.
        """
        collection_count = self._collection.count()
        if collection_count == 0:
            return []

        effective_n = min(n_results, collection_count)
        query_embedding = self._embed([transcript])[0]

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=effective_n,
            include=["documents", "metadatas", "distances"],
        )

        ids: list[str] = results["ids"][0]
        documents: list[str] = results["documents"][0]  # type: ignore[index]
        metadatas: list[dict[str, Any]] = results["metadatas"][0]  # type: ignore[index]
        distances: list[float] = results["distances"][0]  # type: ignore[index]

        historical: list[HistoricalRadio] = []
        for doc_id, document, metadata, distance in zip(
            ids, documents, metadatas, distances, strict=True
        ):
            similarity = max(0.0, min(1.0, 1.0 - float(distance)))
            historical.append(
                self._metadata_to_historical(doc_id, document, metadata, similarity)
            )
        return historical

    async def query_async(self, transcript: str, n_results: int = 5) -> list[HistoricalRadio]:
        """
        Async wrapper around query that offloads embedding to a worker thread.

        Args:
            transcript: Query transcript text.
            n_results: Maximum number of results to return.

        Returns:
            Ranked list of HistoricalRadio records.
        """
        return await asyncio.to_thread(self.query, transcript, n_results)

    def add_document(self, record: dict[str, Any]) -> str:
        """
        Add a new historical document at runtime.

        Args:
            record: Document dict with all required metadata fields.

        Returns:
            The document ID of the inserted record.

        Raises:
            ValueError: If required fields are missing or the document already exists.
        """
        missing = _REQUIRED_DOCUMENT_FIELDS - set(record.keys())
        if missing:
            raise ValueError(f"Missing required document fields: {sorted(missing)}")

        doc_id = str(record["doc_id"])
        existing = self._collection.get(ids=[doc_id], include=[])
        if existing.get("ids"):
            raise ValueError(f"Document already exists: {doc_id}")

        transcript = str(record["raw_transcript"])
        embedding = self._embed([transcript])[0]
        metadata = self._record_to_metadata(record)

        self._collection.add(
            ids=[doc_id],
            documents=[transcript],
            embeddings=[embedding],
            metadatas=[metadata],
        )
        logger.bind(doc_id=doc_id).info("Added historical radio document")
        return doc_id

    def collection_size(self) -> int:
        """
        Return the number of documents in the collection.

        Returns:
            Document count.
        """
        return self._collection.count()
