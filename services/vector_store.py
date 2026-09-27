"""Replaceable vector-store contract with in-memory and SQLAlchemy adapters."""

from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from typing import Protocol, Sequence

import requests
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.async_models import RagVectorRecord
from schemas.rag import VectorRecord


class VectorStoreError(RuntimeError):
    pass


class VectorStore(Protocol):
    async def add(self, records: Sequence[VectorRecord]) -> None: ...

    async def search(
        self,
        vector: Sequence[float],
        *,
        namespace: str,
        limit: int = 5,
        embedding_provider: str | None = None,
        embedding_model: str | None = None,
    ) -> list[tuple[VectorRecord, float]]: ...


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or len(left) != len(right):
        raise ValueError("Cosine similarity requires non-empty vectors of equal dimensions.")
    left_norm = sum(value * value for value in left) ** 0.5
    right_norm = sum(value * value for value in right) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


class InMemoryVectorStore:
    def __init__(self):
        self._records: dict[tuple[str, str], VectorRecord] = {}
        self._lock = asyncio.Lock()

    async def add(self, records: Sequence[VectorRecord]) -> None:
        try:
            async with self._lock:
                for record in records:
                    self._records[(record.namespace, record.id)] = record
        except Exception as exc:
            raise VectorStoreError("Unable to store vectors in memory.") from exc

    async def search(
        self,
        vector: Sequence[float],
        *,
        namespace: str,
        limit: int = 5,
        embedding_provider: str | None = None,
        embedding_model: str | None = None,
    ) -> list[tuple[VectorRecord, float]]:
        if limit < 1:
            raise ValueError("limit must be positive.")
        try:
            async with self._lock:
                candidates = [
                    record
                    for (scope, _), record in self._records.items()
                    if scope == namespace
                    and (embedding_provider is None or record.embedding_provider == embedding_provider)
                    and (embedding_model is None or record.embedding_model == embedding_model)
                ]
            scored = [
                (record, cosine_similarity(vector, record.embedding))
                for record in candidates
                if len(vector) == len(record.embedding)
            ]
            return sorted(scored, key=lambda item: item[1], reverse=True)[:limit]
        except Exception as exc:
            raise VectorStoreError("Unable to search in-memory vectors.") from exc


class SQLAlchemyVectorStore:
    """Persistent adapter; SQL filters namespace and Python ranks matching vectors."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def add(self, records: Sequence[VectorRecord]) -> None:
        if not records:
            return
        try:
            async with self.session_factory() as session:
                for record in records:
                    await session.merge(RagVectorRecord(
                        id=record.id,
                        namespace=record.namespace,
                        text=record.text,
                        embedding=record.embedding,
                        embedding_provider=record.embedding_provider,
                        embedding_model=record.embedding_model,
                        record_metadata=record.metadata,
                        created_at=record.created_at,
                    ))
                await session.commit()
        except Exception as exc:
            raise VectorStoreError("Unable to persist vector records.") from exc

    async def search(
        self,
        vector: Sequence[float],
        *,
        namespace: str,
        limit: int = 5,
        embedding_provider: str | None = None,
        embedding_model: str | None = None,
    ) -> list[tuple[VectorRecord, float]]:
        if limit < 1:
            raise ValueError("limit must be positive.")
        try:
            async with self.session_factory() as session:
                statement = select(RagVectorRecord).where(RagVectorRecord.namespace == namespace)
                if embedding_provider:
                    statement = statement.where(RagVectorRecord.embedding_provider == embedding_provider)
                if embedding_model:
                    statement = statement.where(RagVectorRecord.embedding_model == embedding_model)
                rows = (await session.scalars(statement)).all()
            matches = []
            for row in rows:
                if len(vector) != len(row.embedding):
                    continue
                record = VectorRecord(
                    id=row.id,
                    namespace=row.namespace,
                    text=row.text,
                    embedding=row.embedding,
                    embedding_provider=row.embedding_provider,
                    embedding_model=row.embedding_model,
                    metadata=row.record_metadata or {},
                    created_at=row.created_at,
                )
                matches.append((record, cosine_similarity(vector, record.embedding)))
            return sorted(matches, key=lambda item: item[1], reverse=True)[:limit]
        except Exception as exc:
            raise VectorStoreError("Unable to retrieve persisted vectors.") from exc


class QdrantVectorStore:
    """Qdrant REST adapter with isolated collections per embedding model."""

    def __init__(
        self,
        url: str | None = None,
        *,
        api_key: str | None = None,
        collection_prefix: str = "winged_tycoons_rag",
        timeout: float = 10.0,
        retries: int = 3,
    ):
        self.url = (url or os.getenv("QDRANT_URL", "")).rstrip("/")
        if not self.url:
            raise ValueError("QDRANT_URL is required for QdrantVectorStore.")
        self.api_key = api_key or os.getenv("QDRANT_API_KEY")
        self.collection_prefix = collection_prefix
        self.timeout = timeout
        self.retries = max(1, retries)
        self._collections: set[str] = set()
        self._session = requests.Session()

    async def add(self, records: Sequence[VectorRecord]) -> None:
        try:
            await asyncio.to_thread(self._add_sync, records)
        except Exception as exc:
            if isinstance(exc, VectorStoreError):
                raise
            raise VectorStoreError("Unable to write vectors to Qdrant.") from exc

    async def search(
        self,
        vector: Sequence[float],
        *,
        namespace: str,
        limit: int = 5,
        embedding_provider: str | None = None,
        embedding_model: str | None = None,
    ) -> list[tuple[VectorRecord, float]]:
        if limit < 1:
            raise ValueError("limit must be positive.")
        if not embedding_provider or not embedding_model:
            raise ValueError("Qdrant searches require the query embedding provider and model.")
        try:
            return await asyncio.to_thread(
                self._search_sync,
                vector,
                namespace,
                limit,
                embedding_provider,
                embedding_model,
            )
        except Exception as exc:
            if isinstance(exc, VectorStoreError):
                raise
            raise VectorStoreError("Unable to retrieve vectors from Qdrant.") from exc

    def _add_sync(self, records: Sequence[VectorRecord]) -> None:
        grouped: dict[str, list[dict]] = {}
        for record in records:
            collection = self._collection(record.embedding_provider, record.embedding_model, len(record.embedding))
            self._ensure_collection(collection, len(record.embedding))
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{record.namespace}:{record.id}"))
            grouped.setdefault(collection, []).append({
                "id": point_id,
                "vector": record.embedding,
                "payload": {
                    "id": record.id,
                    "namespace": record.namespace,
                    "text": record.text,
                    "embedding_provider": record.embedding_provider,
                    "embedding_model": record.embedding_model,
                    "metadata": record.metadata,
                    "created_at": record.created_at.isoformat(),
                },
            })
        for collection, points in grouped.items():
            self._request("PUT", f"/collections/{collection}/points?wait=true", json={"points": points})

    def _search_sync(
        self,
        vector: Sequence[float],
        namespace: str,
        limit: int,
        provider: str,
        model: str,
    ) -> list[tuple[VectorRecord, float]]:
        collection = self._collection(provider, model, len(vector))
        self._ensure_collection(collection, len(vector))
        response = self._request(
            "POST",
            f"/collections/{collection}/points/search",
            json={
                "vector": list(vector),
                "limit": limit,
                "with_payload": True,
                "with_vector": True,
                "filter": {"must": [{"key": "namespace", "match": {"value": namespace}}]},
            },
        )
        matches = []
        for point in response.json().get("result", []):
            payload = point["payload"]
            matches.append((VectorRecord(
                id=payload["id"],
                namespace=payload["namespace"],
                text=payload["text"],
                embedding=point.get("vector") or list(vector),
                embedding_provider=payload["embedding_provider"],
                embedding_model=payload["embedding_model"],
                metadata=payload.get("metadata", {}),
                created_at=payload.get("created_at"),
            ), float(point["score"])))
        return matches

    def _ensure_collection(self, collection: str, dimensions: int) -> None:
        if collection in self._collections:
            return
        response = self._request("GET", f"/collections/{collection}", allow_not_found=True)
        if response.status_code == 404:
            self._request(
                "PUT",
                f"/collections/{collection}",
                json={"vectors": {"size": dimensions, "distance": "Cosine"}},
                allow_conflict=True,
            )
        self._collections.add(collection)

    def _request(self, method: str, path: str, *, json: dict | None = None, allow_not_found: bool = False, allow_conflict: bool = False):
        headers = {"api-key": self.api_key} if self.api_key else {}
        error: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = self._session.request(
                    method,
                    f"{self.url}{path}",
                    headers=headers,
                    json=json,
                    timeout=self.timeout,
                )
                if allow_not_found and response.status_code == 404:
                    return response
                if allow_conflict and response.status_code == 409:
                    return response
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                error = exc
                if attempt + 1 < self.retries:
                    time.sleep(0.2 * 2**attempt)
        raise VectorStoreError(f"Qdrant request failed ({method} {path}).") from error

    def _collection(self, provider: str, model: str, dimensions: int) -> str:
        suffix = re.sub(r"[^a-z0-9]+", "_", f"{provider}_{model}".lower()).strip("_")
        return f"{self.collection_prefix}_{suffix}_{dimensions}"


def create_vector_store_from_environment() -> VectorStore:
    if os.getenv("QDRANT_URL", "").strip():
        return QdrantVectorStore()
    if os.getenv("DATABASE_URL", "").strip():
        from services.async_database import create_engine_from_environment

        engine = create_engine_from_environment()
        return SQLAlchemyVectorStore(async_sessionmaker(engine, expire_on_commit=False))
    return InMemoryVectorStore()