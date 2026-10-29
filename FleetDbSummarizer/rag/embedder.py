"""
Nomic Embed Text, run locally with sentence-transformers (no external API call).

Nomic models are trained with task prefixes: stored chunks are embedded as
"search_document: ..." and user questions as "search_query: ...". Vectors are
L2-normalized so pgvector's cosine distance (<=>) gives the similarity.
"""

import logging
import threading
from typing import List

from FleetDbSummarizer.rag import settings

logger = logging.getLogger(__name__)

_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer  # heavy import: only when RAG is used

                logger.info("Loading embedding model %s on %s", settings.EMBED_MODEL, settings.EMBED_DEVICE)
                _model = SentenceTransformer(settings.EMBED_MODEL, trust_remote_code=True, device=settings.EMBED_DEVICE)
                dim = _model.get_sentence_embedding_dimension()
                if dim != settings.EMBED_DIM:
                    raise RuntimeError(f"{settings.EMBED_MODEL} outputs {dim} dims but FLEETI_EMBED_DIM={settings.EMBED_DIM}")
    return _model


def embed_documents(texts: List[str], batch_size: int = 32) -> List[List[float]]:
    vectors = _get_model().encode(
        [f"search_document: {t}" for t in texts], batch_size=batch_size,
        normalize_embeddings=True, show_progress_bar=len(texts) > 100,
    )
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> List[float]:
    return _get_model().encode(f"search_query: {text}", normalize_embeddings=True).tolist()


def warm_up() -> None:
    """Load the model ahead of the first question (it takes a few seconds)."""
    embed_query("warm up")
