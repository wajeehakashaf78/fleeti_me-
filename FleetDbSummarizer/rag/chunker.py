"""
Atomic chunking of the DB knowledge folder.

One chunk = one self-contained fact, so a search hit is exactly the piece the model needs:
  collection  - purpose / use for / do-not-confuse of one collection
  field       - one field line ("- path: type (note)") of one section
  enum        - the allowed values of one field
  note        - one note of one collection
  example     - one example question (the query itself is carried in the payload)

Every chunk text names its collection, so it still makes sense on its own.
Joins and rules are NOT chunked: they are always given exactly, never "probably".
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

from FleetDbSummarizer.knowledge import Knowledge


@dataclass
class Chunk:
    id: str
    kind: str          # collection | field | enum | note | example
    collection: str    # owning collection ("" for multi-collection examples)
    section: str
    text: str          # what gets embedded
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(f"{self.kind}|{self.text}|{sorted(self.payload.items())}".encode("utf-8")).hexdigest()


def _short(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\[\]<>-]+", "_", text)[:120]


def build_chunks(k: Knowledge) -> List[Chunk]:
    chunks: List[Chunk] = []

    for name, info in k.collections.items():
        purpose = _short(info.purpose)
        chunks.append(Chunk(
            id=f"collection:{name}", kind="collection", collection=name, section="",
            text=f"Collection {name}: {info.purpose} Use for: {info.use_for} Not: {info.not_confuse}",
        ))

        for section in k.sections_of(name):
            sec_note = info.section_notes.get(section, "")
            for n, line in enumerate(k.section_fields.get(section, [])):
                path, sep, rest = line[2:].partition(":")
                path = path.strip()
                if not sep or path.startswith("(") or " " in path:  # free-text note inside a field file
                    chunks.append(Chunk(
                        id=f"note:{name}:{section}:{n}", kind="note", collection=name, section=section,
                        text=f"{name} note ({section}): {line[2:].strip()}", payload={"line": line[2:].strip()},
                    ))
                    continue
                chunks.append(Chunk(
                    id=f"field:{name}:{section}:{_slug(path)}", kind="field", collection=name, section=section,
                    text=f"{name}.{path} - {rest.strip()}. "
                         f"Section {section}{' (' + sec_note + ')' if sec_note else ''}. {name}: {purpose}",
                    payload={"line": line},
                ))

        for enum in info.enums:
            fname = enum.split(":", 1)[0].strip()
            chunks.append(Chunk(
                id=f"enum:{name}:{_slug(fname)}", kind="enum", collection=name, section="",
                text=f"{name}.{fname} allowed values: {enum.split(':', 1)[1].strip()}",
                payload={"line": enum},
            ))

        for i, note in enumerate(info.notes):
            chunks.append(Chunk(
                id=f"note:{name}:{i}", kind="note", collection=name, section="",
                text=f"{name} note: {note}", payload={"line": note},
            ))

    for ex in k.examples:
        chunks.append(Chunk(
            id=f"example:{ex.key}", kind="example", collection=",".join(ex.collections), section="",
            text=f"{ex.question} (collections: {', '.join(ex.collections)}; topics: {', '.join(ex.tags)})",
            payload={"key": ex.key},
        ))

    ids = [c.id for c in chunks]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"Duplicate chunk ids: {sorted(dupes)[:5]}")
    return chunks
