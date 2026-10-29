"""
Postgres + pgvector storage for RAG chunks, searched through an HNSW index (cosine).

Table (created by ensure_schema):
  id, kind, collection, section, content, payload (jsonb), content_hash, model, embedding vector(DIM)
"""

import json
import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from FleetDbSummarizer.rag import settings

logger = logging.getLogger(__name__)

_conn = None
_lock = threading.Lock()


@dataclass
class Hit:
    id: str
    kind: str
    collection: str
    section: str
    content: str
    payload: Dict[str, Any]
    score: float  # cosine similarity, 1.0 = identical


def _connect():
    import psycopg
    from pgvector.psycopg import register_vector

    if not settings.PG_DSN:
        raise RuntimeError("FLEETI_PG_DSN is not set")
    conn = psycopg.connect(settings.PG_DSN, autocommit=True, connect_timeout=5)
    register_vector(conn)
    return conn


def _run(fn):
    """Run fn(conn) on the shared connection; reconnect once if it was dropped."""
    global _conn
    with _lock:
        for attempt in (1, 2):
            try:
                if _conn is None or _conn.closed:
                    _conn = _connect()
                return fn(_conn)
            except Exception as exc:
                import psycopg

                if attempt == 1 and isinstance(exc, psycopg.OperationalError):
                    _conn = None
                    continue
                raise


def ensure_schema() -> None:
    t = settings.TABLE

    def go(conn):
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        from pgvector.psycopg import register_vector
        register_vector(conn)  # the vector type exists only after CREATE EXTENSION
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {t} (
                id           text PRIMARY KEY,
                kind         text NOT NULL,
                collection   text NOT NULL DEFAULT '',
                section      text NOT NULL DEFAULT '',
                content      text NOT NULL,
                payload      jsonb NOT NULL DEFAULT '{{}}',
                content_hash text NOT NULL,
                model        text NOT NULL,
                embedding    vector({settings.EMBED_DIM}) NOT NULL,
                updated_at   timestamptz NOT NULL DEFAULT now()
            )""")
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS {t}_embedding_hnsw ON {t}
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = {settings.HNSW_M}, ef_construction = {settings.HNSW_EF_CONSTRUCTION})""")
        conn.execute(f"CREATE INDEX IF NOT EXISTS {t}_kind_collection ON {t} (kind, collection)")

    _run(go)


def existing_hashes() -> Dict[str, tuple]:
    """id -> (content_hash, model) for every stored chunk."""
    return dict(_run(lambda c: {r[0]: (r[1], r[2]) for r in c.execute(
        f"SELECT id, content_hash, model FROM {settings.TABLE}").fetchall()}))


def upsert(rows: Iterable[Dict[str, Any]]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    import numpy as np

    def go(conn):
        with conn.cursor() as cur:
            cur.executemany(f"""
                INSERT INTO {settings.TABLE} (id, kind, collection, section, content, payload, content_hash, model, embedding)
                VALUES (%(id)s, %(kind)s, %(collection)s, %(section)s, %(content)s, %(payload)s, %(content_hash)s, %(model)s, %(embedding)s)
                ON CONFLICT (id) DO UPDATE SET
                    kind = EXCLUDED.kind, collection = EXCLUDED.collection, section = EXCLUDED.section,
                    content = EXCLUDED.content, payload = EXCLUDED.payload, content_hash = EXCLUDED.content_hash,
                    model = EXCLUDED.model, embedding = EXCLUDED.embedding, updated_at = now()""",
                [{**r, "payload": json.dumps(r["payload"]), "embedding": np.asarray(r["embedding"], dtype=np.float32)}
                 for r in rows])
        return len(rows)

    return _run(go)


def delete(ids: Sequence[str]) -> int:
    if not ids:
        return 0
    return _run(lambda c: c.execute(f"DELETE FROM {settings.TABLE} WHERE id = ANY(%s)", (list(ids),)).rowcount)


def count() -> int:
    return _run(lambda c: c.execute(f"SELECT count(*) FROM {settings.TABLE}").fetchone()[0])


def models() -> Dict[str, int]:
    """Embedding model -> number of chunks embedded with it."""
    return dict(_run(lambda c: c.execute(
        f"SELECT model, count(*) FROM {settings.TABLE} GROUP BY model").fetchall()))


def search(query_vec: List[float], kinds: Sequence[str], k: int,
           collections: Optional[Sequence[str]] = None) -> List[Hit]:
    """Nearest chunks by cosine similarity (HNSW), optionally limited to some collections."""
    import numpy as np

    sql = f"""SELECT id, kind, collection, section, content, payload, 1 - (embedding <=> %(q)s) AS score
              FROM {settings.TABLE}
              WHERE kind = ANY(%(kinds)s) {"AND collection = ANY(%(colls)s)" if collections else ""}
              ORDER BY embedding <=> %(q)s
              LIMIT %(k)s"""
    params = {"q": np.asarray(query_vec, dtype=np.float32), "kinds": list(kinds), "colls": list(collections or []), "k": k}

    def go(conn):
        with conn.transaction():
            conn.execute(f"SET LOCAL hnsw.ef_search = {settings.HNSW_EF_SEARCH}")
            return [Hit(*row[:5], row[5] if isinstance(row[5], dict) else json.loads(row[5]), float(row[6]))
                    for row in conn.execute(sql, params).fetchall()]

    return _run(go)
