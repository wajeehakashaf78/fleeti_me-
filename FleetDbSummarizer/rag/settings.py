"""RAG settings, read from the environment (.env)."""

import os

from dotenv import load_dotenv

load_dotenv()

# "auto" = use RAG when Postgres is reachable and the index is built; "1" = always try; "0" = off.
RAG_ENABLED = (os.getenv("FLEETI_RAG_ENABLED") or "auto").strip().lower()

# Postgres with the pgvector extension, e.g. postgresql://user:pass@localhost:5432/fleeti_rag
PG_DSN = (os.getenv("FLEETI_PG_DSN") or "").strip()
TABLE = os.getenv("FLEETI_RAG_TABLE") or "fleeti_rag_chunks"

# Nomic Embed Text. v2 MoE is multilingual (Arabic + English); v1.5 is English-only:
#   nomic-ai/nomic-embed-text-v2-moe  |  nomic-ai/nomic-embed-text-v1.5
# After changing the model run:  python -m FleetDbSummarizer.rag.build_index --full
EMBED_MODEL = os.getenv("FLEETI_EMBED_MODEL") or "nomic-ai/nomic-embed-text-v2-moe"
EMBED_DIM = int(os.getenv("FLEETI_EMBED_DIM") or "768")
EMBED_DEVICE = os.getenv("FLEETI_EMBED_DEVICE") or "cpu"

# Multilingual cross-encoder reranker, applied to the pgvector candidates.
RERANK_ENABLED = (os.getenv("FLEETI_RERANK_ENABLED") or "1").strip().lower() not in ("0", "false", "off", "no")
RERANK_MODEL = os.getenv("FLEETI_RERANK_MODEL") or "BAAI/bge-reranker-v2-m3"
RERANK_MAX_LENGTH = int(os.getenv("FLEETI_RERANK_MAX_LENGTH") or "256")
# Which hit kinds the reranker scores: examples, fields, related. It costs ~130 ms per
# candidate on CPU, so by default only examples (8 pairs, ~1 s); the rest use cosine cut-offs.
# Measured (tests/eval_rag.py): reranking fields/related too added ~1.2 s and no accuracy.
RERANK_SCOPE = {s.strip() for s in (os.getenv("FLEETI_RERANK_SCOPE") or "examples").split(",") if s.strip()}
# How many pgvector candidates the reranker reads (recall). More = better recall, slower.
CANDIDATES_EXAMPLES = int(os.getenv("FLEETI_RAG_CANDIDATES_EXAMPLES") or "8")
CANDIDATES_FIELDS = int(os.getenv("FLEETI_RAG_CANDIDATES_FIELDS") or "12")
CANDIDATES_COLLECTIONS = int(os.getenv("FLEETI_RAG_CANDIDATES_COLLECTIONS") or "4")
# Reranker cut-offs (0..1): keep a hit when it is >= the floor and >= ratio x the best score.
# bge-reranker scores question-vs-question pairs very low (~0.001-0.01), so examples are
# kept relative to the best one only.
RERANK_EXAMPLE_MIN = float(os.getenv("FLEETI_RERANK_EXAMPLE_MIN") or "0")
RERANK_EXAMPLE_RATIO = float(os.getenv("FLEETI_RERANK_EXAMPLE_RATIO") or "0.5")
RERANK_FIELD_MIN = float(os.getenv("FLEETI_RERANK_FIELD_MIN") or "0")
RERANK_FIELD_RATIO = float(os.getenv("FLEETI_RERANK_FIELD_RATIO") or "0.5")
RERANK_RELATED_MIN = float(os.getenv("FLEETI_RERANK_RELATED_MIN") or "0.05")
RERANK_RELATED_RATIO = float(os.getenv("FLEETI_RERANK_RELATED_RATIO") or "0.5")

# HNSW index build/search parameters (pgvector).
HNSW_M = int(os.getenv("FLEETI_HNSW_M") or "16")
HNSW_EF_CONSTRUCTION = int(os.getenv("FLEETI_HNSW_EF_CONSTRUCTION") or "64")
HNSW_EF_SEARCH = int(os.getenv("FLEETI_HNSW_EF_SEARCH") or "100")

# How much to retrieve per get_query_context call (upper bounds).
TOP_EXAMPLES = int(os.getenv("FLEETI_RAG_TOP_EXAMPLES") or "3")
TOP_FIELDS = int(os.getenv("FLEETI_RAG_TOP_FIELDS") or "12")
TOP_RELATED = int(os.getenv("FLEETI_RAG_TOP_RELATED") or "2")

# Cosine cut-offs, used for whatever the reranker does not score. Scores shift from question
# to question, so a hit is kept only when it is close to the best hit of its kind ("margin")
# and above a floor. Calibrated for nomic-embed-text-v2-moe (its scores run ~0.2-0.5;
# v1.5 values were 0.62 / 0.06 / 0.60). Re-check with tests/eval_rag.py after a model change.
EXAMPLE_MARGIN = float(os.getenv("FLEETI_RAG_EXAMPLE_MARGIN") or "0.05")
FIELD_MIN_SCORE = float(os.getenv("FLEETI_RAG_FIELD_MIN_SCORE") or "0.30")
FIELD_MARGIN = float(os.getenv("FLEETI_RAG_FIELD_MARGIN") or "0.04")
RELATED_MIN_SCORE = float(os.getenv("FLEETI_RAG_RELATED_MIN_SCORE") or "0.32")
RELATED_MARGIN = float(os.getenv("FLEETI_RAG_RELATED_MARGIN") or "0.03")

# After a failed Postgres check, wait this long before trying again.
RETRY_SECONDS = int(os.getenv("FLEETI_RAG_RETRY_SECONDS") or "300")
