"""
Build or refresh the RAG index from FleetDbSummarizer/db_knowledge/.

    python -m FleetDbSummarizer.rag.build_index            # incremental: only changed chunks are re-embedded
    python -m FleetDbSummarizer.rag.build_index --full     # re-embed everything (e.g. after changing the model)
    python -m FleetDbSummarizer.rag.build_index --dry-run  # show the chunks, no Postgres needed

Run it again after editing any db_knowledge/*.txt file.
"""

import argparse
import logging
import sys
import time
from collections import Counter

from FleetDbSummarizer.knowledge import load_knowledge
from FleetDbSummarizer.rag import settings
from FleetDbSummarizer.rag.chunker import build_chunks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--full", action="store_true", help="re-embed every chunk")
    parser.add_argument("--dry-run", action="store_true", help="only build and count chunks")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    chunks = build_chunks(load_knowledge())
    print(f"{len(chunks)} chunks: {dict(Counter(c.kind for c in chunks))}")
    if args.dry_run:
        for c in chunks[:5] + [c for c in chunks if c.kind == "example"][:2]:
            print(f"  [{c.kind}] {c.id}\n      {c.text[:160]}")
        return 0

    from FleetDbSummarizer.rag import embedder, store

    store.ensure_schema()
    stored = store.existing_hashes()
    todo = [c for c in chunks if args.full or stored.get(c.id) != (c.content_hash, settings.EMBED_MODEL)]
    stale = sorted(set(stored) - {c.id for c in chunks})
    print(f"model={settings.EMBED_MODEL}  to embed={len(todo)}  unchanged={len(chunks) - len(todo)}  to delete={len(stale)}")

    started = time.time()
    if todo:
        vectors = embedder.embed_documents([c.text for c in todo])
        store.upsert({
            "id": c.id, "kind": c.kind, "collection": c.collection, "section": c.section, "content": c.text,
            "payload": c.payload, "content_hash": c.content_hash, "model": settings.EMBED_MODEL, "embedding": v,
        } for c, v in zip(todo, vectors))
    deleted = store.delete(stale)
    print(f"done in {time.time() - started:.1f}s - embedded {len(todo)}, deleted {deleted}, total in index {store.count()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
