"""Embedding-based semantic evaluation for generated answers."""

from __future__ import annotations

import asyncio

from schemas.rag import SemanticEvaluation
from services.embeddings import EmbeddingService
from services.vector_store import cosine_similarity


class SemanticEvaluationError(RuntimeError):
    pass


class SemanticEvaluator:
    def __init__(self, embedding_service: EmbeddingService, threshold: float = 0.75):
        if not -1.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between -1 and 1.")
        self.embedding_service = embedding_service
        self.threshold = threshold

    async def evaluate(self, user_query: str, reference_answer: str, model_output: str) -> SemanticEvaluation:
        if not reference_answer.strip() or not model_output.strip():
            raise ValueError("Reference answer and model output must not be empty.")
        try:
            batch = await asyncio.to_thread(
                self.embedding_service.embed,
                [reference_answer, model_output],
                preferred_provider="openai",
            )
            score = cosine_similarity(batch.vectors[0], batch.vectors[1])
        except Exception as exc:
            raise SemanticEvaluationError("Unable to generate or compare semantic evaluation embeddings.") from exc
        score = max(-1.0, min(1.0, score))
        return SemanticEvaluation(
            user_query=user_query,
            reference_answer=reference_answer,
            model_output=model_output,
            similarity=score,
            threshold=self.threshold,
            passed=score >= self.threshold,
            similarity_delta=score - self.threshold,
            embedding_model=batch.model,
        )