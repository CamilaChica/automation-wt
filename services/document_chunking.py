"""Fixed, overlapping, recursive, and embedding-aware document chunking."""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any, Sequence

from schemas.rag import DocumentChunk
from services.embeddings import EmbeddingService


class DocumentProcessor:
    def __init__(
        self,
        *,
        chunk_size: int = 1000,
        overlap: int = 100,
        embedding_service: EmbeddingService | None = None,
        semantic_threshold: float = 0.72,
    ):
        if chunk_size < 1 or overlap < 0 or overlap >= chunk_size:
            raise ValueError("chunk_size must be positive and overlap must be smaller than chunk_size.")
        if not -1 <= semantic_threshold <= 1:
            raise ValueError("semantic_threshold must be between -1 and 1.")
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.embedding_service = embedding_service or EmbeddingService()
        self.semantic_threshold = semantic_threshold

    def fixed(self, text: str, *, metadata: dict[str, Any] | None = None) -> list[DocumentChunk]:
        return self._build_chunks(self._windows(text, self.chunk_size, 0), "fixed", metadata)

    def overlap_chunks(self, text: str, *, metadata: dict[str, Any] | None = None) -> list[DocumentChunk]:
        return self._build_chunks(self._windows(text, self.chunk_size, self.overlap), "overlap", metadata)

    def recursive(self, text: str, *, metadata: dict[str, Any] | None = None) -> list[DocumentChunk]:
        if not text:
            return []
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter

            pieces = RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.overlap,
                length_function=len,
                separators=["\n\n", ". ", " ", ""],
                keep_separator=True,
            ).split_text(text)
        except ImportError:
            pieces = self._recursive_fallback(text)
        return self._build_chunks(pieces, "recursive", metadata)

    def semantic(self, text: str, *, metadata: dict[str, Any] | None = None) -> list[DocumentChunk]:
        sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text.strip()) if sentence.strip()]
        if not sentences:
            return []
        if len(sentences) == 1:
            return self._build_chunks(self._fit_size(sentences), "semantic", metadata)
        try:
            embeddings = self.embedding_service.embed(sentences).vectors
            groups: list[list[str]] = [[sentences[0]]]
            for index, sentence in enumerate(sentences[1:], start=1):
                similarity = self.cosine_similarity(embeddings[index - 1], embeddings[index])
                candidate = " ".join([*groups[-1], sentence])
                if similarity < self.semantic_threshold or len(candidate) > self.chunk_size:
                    groups.append([sentence])
                else:
                    groups[-1].append(sentence)
            pieces = [piece for group in groups for piece in self._windows(" ".join(group), self.chunk_size, self.overlap)]
            return self._build_chunks(pieces, "semantic", metadata)
        except Exception:
            return self._build_chunks(self._recursive_fallback(text), "semantic_fallback", metadata)

    def _recursive_fallback(self, text: str) -> list[str]:
        remaining = text
        pieces: list[str] = []
        for separator in ("\n\n", ". ", " "):
            if len(remaining) <= self.chunk_size:
                break
            sections = remaining.split(separator)
            if len(sections) == 1:
                continue
            current = ""
            rebuilt: list[str] = []
            for section in sections:
                candidate = section if not current else current + separator + section
                if current and len(candidate) > self.chunk_size:
                    rebuilt.append(current)
                    current = section
                else:
                    current = candidate
            if current:
                rebuilt.append(current)
            pieces.extend(
                chunk
                for piece in rebuilt[:-1]
                for chunk in self._windows(piece, self.chunk_size, self.overlap)
            )
            remaining = rebuilt[-1] if rebuilt else ""
        pieces.extend(self._windows(remaining, self.chunk_size, self.overlap))
        return pieces

    def _fit_size(self, pieces: Sequence[str]) -> list[str]:
        return [chunk for piece in pieces for chunk in self._windows(piece, self.chunk_size, self.overlap)]

    @staticmethod
    def _windows(text: str, size: int, overlap: int) -> list[str]:
        if not text:
            return []
        step = size - overlap
        return [text[start : start + size] for start in range(0, len(text), step)]

    @staticmethod
    def _build_chunks(pieces: Sequence[str], strategy: str, metadata: dict[str, Any] | None) -> list[DocumentChunk]:
        source_metadata = dict(metadata or {})
        document_id = str(source_metadata.get("document_id") or uuid.uuid4())
        chunk_id_prefix = hashlib.sha256(document_id.encode("utf-8")).hexdigest()[:32]
        if strategy == "fixed":
            source_metadata["boundary_context"] = "No overlap; context at chunk edges may be lost."
        elif strategy == "overlap":
            source_metadata["boundary_context"] = "Adjacent chunks share text to preserve boundary context."
        return [
            DocumentChunk(
                id=f"{chunk_id_prefix}:{index}",
                text=piece,
                metadata={
                    **source_metadata,
                    "document_id": document_id,
                    "chunking_strategy": strategy,
                    "chunk_index": index,
                },
                index=index,
            )
            for index, piece in enumerate(pieces)
            if piece.strip()
        ]

    @staticmethod
    def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
        if not left or len(left) != len(right):
            raise ValueError("Cosine similarity requires non-empty vectors of equal dimensions.")
        left_norm = sum(value * value for value in left) ** 0.5
        right_norm = sum(value * value for value in right) ** 0.5
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)