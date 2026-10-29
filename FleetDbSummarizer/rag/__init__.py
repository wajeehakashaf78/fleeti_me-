"""
RAG for the FLEETI agent over atomic chunks of FleetDbSummarizer/db_knowledge/:
  1. Nomic Embed Text (multilingual v2) turns the question into a vector,
  2. Postgres/pgvector (HNSW) fetches candidate chunks,
  3. a multilingual cross-encoder (bge-reranker-v2-m3) re-scores them; the best few are kept.

RAG only CHOOSES which examples and extra field details to show. The collection menu,
joins and all rules stay deterministic. If Postgres or the index is unavailable,
retrieve() returns None and the caller falls back to keyword matching.

Build / refresh the index:   python -m FleetDbSummarizer.rag.build_index
"""

import logging
import time
from typing import Any, Dict, List, Optional, Sequence

from FleetDbSummarizer.rag import settings

logger = logging.getLogger(__name__)

_state = {"ok": None, "checked_at": 0.0, "reason": ""}


def status() -> Dict[str, Any]:
    return {"enabled": settings.RAG_ENABLED, "available": bool(_state["ok"]), "reason": _state["reason"],
            "model": settings.EMBED_MODEL,
            "reranker": settings.RERANK_MODEL if settings.RERANK_ENABLED else None}


def warm_up() -> None:
    """Load the embedding model (and reranker) ahead of the first question."""
    from FleetDbSummarizer.rag import embedder

    embedder.warm_up()
    if settings.RERANK_ENABLED:
        from FleetDbSummarizer.rag import reranker

        reranker.warm_up()


def available() -> bool:
    """True when RAG is switched on, Postgres answers and the index has chunks (cached)."""
    if settings.RAG_ENABLED in ("0", "false", "off", "no"):
        return False
    if settings.RAG_ENABLED == "auto" and not settings.PG_DSN:
        _state.update(ok=False, reason="FLEETI_PG_DSN not set")
        return False
    now = time.time()
    if _state["ok"] is not None and (_state["ok"] or now - _state["checked_at"] < settings.RETRY_SECONDS):
        return bool(_state["ok"])
    try:
        from FleetDbSummarizer.rag import store

        built = store.models()
        if not built:
            _state.update(ok=False, reason="index is empty - run build_index")
        elif set(built) != {settings.EMBED_MODEL}:
            # Vectors from different models are not comparable: searching would return noise.
            _state.update(ok=False, reason=f"index was built with {sorted(built)} but FLEETI_EMBED_MODEL="
                                           f"{settings.EMBED_MODEL} - run build_index --full")
        else:
            _state.update(ok=True, reason="")
    except Exception as exc:  # Postgres down, extension missing, packages missing...
        _state.update(ok=False, reason=f"{type(exc).__name__}: {str(exc)[:200]}")
    _state["checked_at"] = now
    if not _state["ok"]:
        logger.warning("RAG unavailable, using keyword fallback: %s", _state["reason"])
    return bool(_state["ok"])


def _mark_failed(exc: Exception) -> None:
    _state.update(ok=False, checked_at=time.time(), reason=f"{type(exc).__name__}: {str(exc)[:200]}")
    logger.warning("RAG search failed, using keyword fallback: %s", _state["reason"])


def retrieve(query: str, collections: Sequence[str]) -> Optional[Dict[str, Any]]:
    """
    Semantic search for one get_query_context call.

    Returns None when RAG is unavailable, else:
      examples:  [example keys]                 best-matching example queries (any collection)
      fields:    {collection: [field lines]}    relevant fields of the requested collections
      related:   [(collection, score)]          other collections that look relevant
    (Enums and notes of the requested collections are always given in full by the caller.)
    """
    if not query.strip() or not available():
        return None
    scope = settings.RERANK_SCOPE if settings.RERANK_ENABLED else set()
    try:
        from FleetDbSummarizer.rag import embedder, store

        # Stage 1 - pgvector (HNSW): fetch candidates. Wider for the kinds the reranker scores.
        q = embedder.embed_query(query)
        examples = store.search(q, ["example"], settings.CANDIDATES_EXAMPLES if "examples" in scope else settings.TOP_EXAMPLES)
        fields = (store.search(q, ["field"], settings.CANDIDATES_FIELDS if "fields" in scope else settings.TOP_FIELDS,
                               collections) if collections else [])
        related = [h for h in store.search(q, ["collection"], settings.CANDIDATES_COLLECTIONS + len(collections))
                   if h.collection not in collections]

        # Stage 2 - cross-encoder reranker: re-score those candidates against the question.
        reranked = {"examples": examples, "fields": fields, "related": related}
        pool = [h for kind, hits in reranked.items() if kind in scope for h in hits]
        if pool:
            from FleetDbSummarizer.rag import reranker

            for h, s in zip(pool, reranker.score(query, [h.content for h in pool])):
                h.score = s
            for kind in scope:
                reranked.get(kind, []).sort(key=lambda h: h.score, reverse=True)
    except Exception as exc:
        _mark_failed(exc)
        return None

    def keep_reranked(hits, floor: float, ratio: float, limit: int):
        """Reranker scores are 0..1: keep hits above a floor and >= ratio x the best one."""
        best = hits[0].score if hits else 0.0
        return [h for h in hits if h.score >= max(floor, best * ratio)][:limit]

    def keep_cosine(hits, margin: float, floor: float, limit: int):
        """Cosine scores shift per question: keep hits close to the best one, above a floor."""
        best = hits[0].score if hits else 0.0
        return [h for h in hits if h.score >= max(best - margin, floor)][:limit]

    ex_hits = (keep_reranked(examples, settings.RERANK_EXAMPLE_MIN, settings.RERANK_EXAMPLE_RATIO, settings.TOP_EXAMPLES)
               if "examples" in scope else keep_cosine(examples, settings.EXAMPLE_MARGIN, 0.0, settings.TOP_EXAMPLES))
    field_hits = (keep_reranked(fields, settings.RERANK_FIELD_MIN, settings.RERANK_FIELD_RATIO, settings.TOP_FIELDS)
                  if "fields" in scope else keep_cosine(fields, settings.FIELD_MARGIN, settings.FIELD_MIN_SCORE, settings.TOP_FIELDS))
    rel_hits = (keep_reranked(related, settings.RERANK_RELATED_MIN, settings.RERANK_RELATED_RATIO, settings.TOP_RELATED)
                if "related" in scope else keep_cosine(related, settings.RELATED_MARGIN, settings.RELATED_MIN_SCORE, settings.TOP_RELATED))

    grouped: Dict[str, List[str]] = {}
    for h in field_hits:
        grouped.setdefault(h.collection, []).append(h.payload.get("line", h.content))

    return {
        "examples": [h.payload["key"] for h in ex_hits],
        "fields": grouped,
        "related": [(h.collection, round(h.score, 3)) for h in rel_hits],
    }
