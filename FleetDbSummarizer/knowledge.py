"""
Loader for the FMS database knowledge folder (FleetDbSummarizer/db_knowledge/).

The .txt files are the single source of truth for DB details - collection purpose,
fields, enums, notes, joins and example queries. Python only reads them; query and
safety RULES stay in Python (FleetiAgent/schema_service.py, FleetiQueryRunner/execute.py).

Layout:
  _overview.txt          sections headed by an UPPER-CASE line (MENTAL MODEL, DISAMBIGUATIONS, ...)
  _relationships.txt     "From | To | Join | Cardinality | Meaning" per line
  _examples.txt          blocks starting with "=== Example"
  <Collection>/_about.txt
  <Collection>/<section>.txt   "- path: type (note)" field lines
"""

import re
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent / "db_knowledge"


@dataclass
class CollectionInfo:
    name: str
    purpose: str = ""
    use_for: str = ""
    not_confuse: str = ""
    tenant: str = ""
    ids: str = ""
    default_sections: List[str] = field(default_factory=list)
    hidden_fields: List[str] = field(default_factory=list)
    enums: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    section_notes: Dict[str, str] = field(default_factory=dict)  # section -> note ("" if none)
    indexes: List[str] = field(default_factory=list)


@dataclass
class Relationship:
    left: str
    right: str
    join: str
    cardinality: str
    meaning: str

    def text(self) -> str:
        return f"{self.left} -> {self.right}: {self.join} ({self.cardinality}; {self.meaning})"


@dataclass
class Example:
    question: str
    query: str
    collections: List[str]
    tags: List[str]

    @property
    def key(self) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self.question.lower()).strip("-")[:80]


@dataclass
class Knowledge:
    collections: Dict[str, CollectionInfo]
    section_fields: Dict[str, List[str]]   # section -> ["- path: type (note)", ...]
    section_parent: Dict[str, str]         # section -> collection
    relationships: List[Relationship]
    overview: Dict[str, str]               # header -> body text
    examples: List[Example]

    def sections_of(self, collection: str) -> List[str]:
        """Sections of a collection, as listed in its _about.txt (base first)."""
        return list(self.collections[collection].section_notes) if collection in self.collections else []


_LIST_HEADERS = {"Enums:": "enums", "Notes:": "notes", "Sections:": "sections", "Indexes:": "indexes"}
_SCALARS = {
    "Purpose": "purpose", "Use for": "use_for", "Do not confuse with": "not_confuse",
    "Tenant field": "tenant", "IDs": "ids",
}


def _split_csv(value: str) -> List[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _parse_about(name: str, text: str) -> CollectionInfo:
    info = CollectionInfo(name=name)
    current: Optional[str] = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line in _LIST_HEADERS:
            current = _LIST_HEADERS[line]
            continue
        if line.startswith("- ") and current:
            item = line[2:].strip()
            if current == "sections":
                sec, _, note = item.partition(":")
                info.section_notes[sec.strip()] = note.strip()
            else:
                getattr(info, current).append(item)
            continue
        current = None
        key, _, value = line.partition(":")
        value = value.strip()
        if key in _SCALARS:
            setattr(info, _SCALARS[key], value)
        elif key == "Default sections":
            info.default_sections = _split_csv(value)
        elif key == "Hidden fields":
            info.hidden_fields = _split_csv(value)
    return info


def _parse_relationships(text: str) -> List[Relationship]:
    rels = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 5:
            rels.append(Relationship(*parts))
        else:
            logger.warning("Skipping malformed relationship line: %s", line[:120])
    return rels


def _parse_overview(text: str) -> Dict[str, str]:
    """Split on UPPER-CASE header lines; the header's first word group is the key."""
    sections: Dict[str, List[str]] = {}
    current = "_intro"
    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z ]+[A-Z])(\s*\(.*\))?\s*$", line)
        if m:
            current = m.group(1).strip()
            sections[current] = [line]
            continue
        sections.setdefault(current, []).append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _parse_examples(text: str) -> List[Example]:
    examples = []
    for block in re.split(r"^=== Example.*$", text, flags=re.M)[1:]:
        fields: Dict[str, str] = {}
        for line in block.strip().splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip() in ("tags", "collections", "question", "query"):
                fields[key.strip()] = value.strip()
        if fields.get("question") and fields.get("query"):
            examples.append(Example(
                question=fields["question"],
                query=fields["query"],
                collections=_split_csv(fields.get("collections", "")),
                tags=_split_csv(fields.get("tags", "")),
            ))
    return examples


def _field_lines(text: str) -> List[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip().startswith("- ")]


@lru_cache(maxsize=1)
def load_knowledge(root: Path = KNOWLEDGE_DIR) -> Knowledge:
    collections: Dict[str, CollectionInfo] = {}
    section_fields: Dict[str, List[str]] = {}
    section_parent: Dict[str, str] = {}

    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        about = folder / "_about.txt"
        if not about.exists():
            logger.warning("Collection folder without _about.txt skipped: %s", folder.name)
            continue
        info = _parse_about(folder.name, about.read_text(encoding="utf-8"))
        for f in sorted(folder.glob("*.txt")):
            if f.name.startswith("_"):
                continue
            section_fields[f.stem] = _field_lines(f.read_text(encoding="utf-8"))
            section_parent[f.stem] = folder.name
            info.section_notes.setdefault(f.stem, "")  # a file not listed in _about still counts
        # Keep _about order (base first); drop listed sections that have no file.
        info.section_notes = {s: n for s, n in info.section_notes.items() if s in section_fields}
        if not info.default_sections:
            info.default_sections = list(info.section_notes)[:1]
        collections[folder.name] = info

    def read(name: str) -> str:
        path = root / name
        return path.read_text(encoding="utf-8") if path.exists() else ""

    knowledge = Knowledge(
        collections=collections,
        section_fields=section_fields,
        section_parent=section_parent,
        relationships=_parse_relationships(read("_relationships.txt")),
        overview=_parse_overview(read("_overview.txt")),
        examples=_parse_examples(read("_examples.txt")),
    )
    logger.info(
        "Loaded DB knowledge: %d collections, %d sections, %d joins, %d examples",
        len(collections), len(section_fields), len(knowledge.relationships), len(knowledge.examples),
    )
    return knowledge
