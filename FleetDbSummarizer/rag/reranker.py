"""
Multilingual cross-encoder reranker (default BAAI/bge-reranker-v2-m3), run locally.

pgvector finds candidates by comparing two separate vectors (fast, rough). The reranker
reads the question and each candidate TOGETHER and scores how well the candidate answers
it (slower, precise), so only the best few reach the model. Works for Arabic and English.
Scores are 0..1 (sigmoid).
"""

import logging
import threading
from typing import List, Sequence

from FleetDbSummarizer.rag import settings

logger = logging.getLogger(__name__)

_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from sentence_transformers import CrossEncoder  # heavy import: only when RAG is used

                logger.info("Loading reranker %s on %s", settings.RERANK_MODEL, settings.EMBED_DEVICE)
                _model = CrossEncoder(settings.RERANK_MODEL, max_length=settings.RERANK_MAX_LENGTH,
                                      device=settings.EMBED_DEVICE)
    return _model


def score(query: str, texts: Sequence[str]) -> List[float]:
    """Relevance of each text to the query, 0..1."""
    if not texts:
        return []
    import torch

    scores = _get_model().predict([(query, t) for t in texts], batch_size=32,
                                  activation_fct=torch.nn.Sigmoid(), show_progress_bar=False)
    return [float(s) for s in scores]


def warm_up() -> None:
    score("warm up", ["warm up"])
