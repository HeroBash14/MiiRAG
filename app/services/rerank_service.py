import asyncio
import logging
import math
import threading
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


def _sigmoid(logit: float) -> float:
    """Mengonversi skor logit Cross-Encoder menjadi probabilitas relevansi [0.0, 1.0]."""
    clamped = max(-50.0, min(50.0, float(logit)))
    return 1.0 / (1.0 + math.exp(-clamped))


class CrossEncoderRerankService:
    """Reranker Cross-Encoder multilingual lokal untuk menyaring dan mengurutkan kandidat chunk."""

    def __init__(self) -> None:
        self._model: Any = None
        self._lock = threading.Lock()

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model

        with self._lock:
            if self._model is not None:
                return self._model

            import torch
            from sentence_transformers import CrossEncoder

            device = settings.RERANK_DEVICE
            model_kwargs: dict[str, Any] = {}

            if device == "cuda" and not torch.cuda.is_available():
                logger.warning("CUDA tidak tersedia untuk reranker, fallback ke CPU.")
                device = "cpu"
            elif device == "cuda":
                model_kwargs["dtype"] = torch.float16

            logger.info(
                "Memuat model reranker '%s' pada device '%s'...",
                settings.RERANK_MODEL,
                device,
            )
            self._model = CrossEncoder(
                settings.RERANK_MODEL,
                device=device,
                max_length=512,
                model_kwargs=model_kwargs if model_kwargs else None,
            )
            logger.info("Model reranker '%s' berhasil dimuat.", settings.RERANK_MODEL)
            return self._model

    def _score_sync(self, query: str, documents: list[str]) -> list[float]:
        model = self._get_model()
        pairs = [(query, doc) for doc in documents]
        raw_scores = model.predict(pairs, batch_size=32, show_progress_bar=False)
        return [_sigmoid(float(s)) for s in raw_scores]

    async def preload(self) -> None:
        """Memuat model reranker ke memori saat startup agar request pertama tetap instan."""
        await asyncio.to_thread(self._get_model)

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        """Menghitung skor relevansi Cross-Encoder (0.0 - 1.0) untuk daftar kandidat dokumen."""
        if not documents:
            return []
        return await asyncio.to_thread(self._score_sync, query, documents)


rerank_service = CrossEncoderRerankService()
