import asyncio
import logging
from collections.abc import Iterable
from typing import Any

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)


def normalize_l2(vector: Iterable[float]) -> list[float]:
    """Normalisasi vector ke panjang unit (L2 norm = 1.0) untuk akurasi cosine similarity."""
    arr = np.asarray(list(vector), dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm > 0.0:
        arr = arr / norm
    return arr.tolist()


class LocalSentenceTransformerEmbeddingService:
    """Embedding model lokal (BAAI/bge-m3) menggunakan SentenceTransformers dengan akselerasi GPU CUDA."""

    def __init__(self) -> None:
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            import torch
            from sentence_transformers import SentenceTransformer

            device = settings.EMBEDDING_DEVICE
            if device == "cuda" and not torch.cuda.is_available():
                logger.warning(
                    "GPU CUDA tidak terdeteksi oleh PyTorch, beralih (fallback) ke CPU."
                )
                device = "cpu"
            elif device == "cuda":
                logger.info(
                    "CUDA terdeteksi: %s (%d MB VRAM)",
                    torch.cuda.get_device_name(0),
                    torch.cuda.get_device_properties(0).total_memory // (1024 * 1024),
                )

            logger.info(
                "Memuat model embedding lokal '%s' pada device '%s'...",
                settings.EMBEDDING_MODEL,
                device,
            )
            self._model = SentenceTransformer(settings.EMBEDDING_MODEL, device=device)
            logger.info("Model '%s' berhasil dimuat ke memori.", settings.EMBEDDING_MODEL)
        return self._model

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        embeddings = model.encode(
            texts,
            batch_size=settings.EMBEDDING_BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [vec.tolist() for vec in embeddings]

    async def preload(self) -> None:
        """Memuat model embedding ke memori saat startup agar query pertama tanpa cold-start."""
        await asyncio.to_thread(self._get_model)

    async def embed_documents(
        self, texts: list[str], title: str | None = None
    ) -> list[list[float]]:
        """Mengubah batch potongan dokumen PDF menjadi vector 1024 dimensi."""
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_sync, texts)

    async def embed_query(self, query: str) -> list[float]:
        """Mengubah query pencarian menjadi vector 1024 dimensi."""
        vectors = await asyncio.to_thread(self._embed_sync, [query])
        return vectors[0]


class VertexEmbeddingService:
    """Fallback ke Vertex AI Gemini Embedding jika EMBEDDING_PROVIDER == 'vertex'."""

    def __init__(self) -> None:
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai

            if not settings.GCP_PROJECT_ID:
                raise RuntimeError("GCP_PROJECT_ID belum dikonfigurasi.")
            self._client = genai.Client(
                vertexai=True,
                project=settings.GCP_PROJECT_ID,
                location=settings.GCP_LOCATION,
            )
        return self._client

    def _embed_sync(
        self,
        contents: list[str],
        task_type: str,
        title: str | None = None,
    ) -> list[list[float]]:
        from google.genai import types

        client = self._get_client()
        config_kwargs: dict = {
            "task_type": task_type,
            "output_dimensionality": settings.EMBEDDING_DIMENSIONS,
        }
        if title and task_type == "RETRIEVAL_DOCUMENT":
            config_kwargs["title"] = title

        response = client.models.embed_content(
            model=settings.EMBEDDING_MODEL,
            contents=contents,
            config=types.EmbedContentConfig(**config_kwargs),
        )
        return [normalize_l2(item.values) for item in response.embeddings]

    async def embed_documents(
        self, texts: list[str], title: str | None = None
    ) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(
            self._embed_sync, texts, "RETRIEVAL_DOCUMENT", title
        )

    async def embed_query(self, query: str) -> list[float]:
        vectors = await asyncio.to_thread(
            self._embed_sync, [query], "RETRIEVAL_QUERY", None
        )
        return vectors[0]


# Pilih service berdasarkan konfigurasi settings.EMBEDDING_PROVIDER
if settings.EMBEDDING_PROVIDER == "vertex":
    embedding_service: Any = VertexEmbeddingService()
else:
    embedding_service = LocalSentenceTransformerEmbeddingService()
