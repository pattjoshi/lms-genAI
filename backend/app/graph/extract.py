"""Concept extraction: an indexed file -> draft concepts + prerequisites in Neo4j (Phase 3).

    chunks (Postgres) -> sections -> LLM (structured output) -> validate -> dedupe -> Neo4j
                                                                                  \\-> failed (+ error)

It runs after the upload pipeline has made the file searchable, with its own status
(`documents.concepts_status`): if the LLM or Neo4j fails here, students can still ask
about the file, and the teacher can retry the extraction alone.

Everything written is a DRAFT. Teachers review drafts before students see them (next part
of Phase 3); an LLM-built graph is a suggestion, not a source of truth.
"""

import difflib
import logging
import re
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage
from neo4j.exceptions import Neo4jError, ServiceUnavailable
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.graph import store
from app.graph.names import clean_name, concept_key, split_acronym
from app.graph.resolve import key_index, resolve
from app.llm.errors import LLMError
from app.llm.service import chat_structured, embed_texts
from app.llm.tracing import observe, trace
from app.models import Chunk, Course, Document, DocumentStatus, Module, Topic, User
from app.prompts.extract_concepts import EXTRACT_SYSTEM, EXTRACT_USER, format_known

log = logging.getLogger(__name__)

MAX_CONCEPTS_PER_PART = 10  # the prompt asks for 3-8; anything beyond 10 is the model ignoring it
MAX_PREREQUISITES = 6
MAX_NAME_WORDS = 8

# ---------------------------------------------------------------------------
# 1. The output schema. Field descriptions are sent to the model as part of the prompt.
#    No defaults: OpenAI's strict mode requires every field, and so do we.
# ---------------------------------------------------------------------------


class ExtractedConcept(BaseModel):
    name: str = Field(description="Concept name, 1-5 words, Title Case. Reuse a known concept name when it fits.")
    definition: str = Field(description="One sentence explaining the concept, based only on the section.")
    prerequisites: list[str] = Field(
        description="Names of concepts a student must understand before this one. Empty list if none."
    )
    evidence: str = Field(description="A short quote (under 25 words) copied word for word from the section.")


class ConceptExtraction(BaseModel):
    concepts: list[ExtractedConcept] = Field(description="The 3 to 8 key concepts this section teaches.")


# ---------------------------------------------------------------------------
# 2. Sections: the LLM reads one heading's worth of text at a time.
# ---------------------------------------------------------------------------


@dataclass
class SectionPart:
    section: str | None
    text: str = ""
    chunks: list[tuple[int, int | None, str]] = field(default_factory=list)  # (chunk_index, page, text)


def _body(chunk_text: str, section: str | None) -> str:
    """The chunker prefixes each chunk with its heading; the section text needs it once."""
    if section and chunk_text.startswith(section + "\n"):
        return chunk_text[len(section) + 1 :]
    return chunk_text


def join_overlapping(a: str, b: str, max_overlap: int = 400) -> str:
    """Neighbouring chunks share CHUNK_OVERLAP characters. Glue them without the repeat."""
    for size in range(min(len(a), len(b), max_overlap), 19, -1):
        if a.endswith(b[:size]):
            return a + b[size:]
    return f"{a}\n{b}"


def build_parts(chunks: list[Chunk], max_chars: int) -> list[SectionPart]:
    """Consecutive chunks with the same heading form a section; long sections are split
    at chunk boundaries so one LLM call never gets more than `max_chars` of text."""
    parts: list[SectionPart] = []
    for c in sorted(chunks, key=lambda c: c.chunk_index):
        body = _body(c.text, c.section)
        current = parts[-1] if parts else None
        if current is None or current.section != c.section or len(current.text) + len(body) > max_chars:
            current = SectionPart(section=c.section)
            parts.append(current)
        current.text = join_overlapping(current.text, body) if current.text else body
        current.chunks.append((c.chunk_index, c.page, c.text))
    return parts


# ---------------------------------------------------------------------------
# 3. Validation: strict JSON guarantees the SHAPE. These checks are about the CONTENT.
# ---------------------------------------------------------------------------


@dataclass
class Found:
    name: str
    key: str
    definition: str
    prerequisites: list[str]  # display names
    evidence: str
    section: str | None
    aliases: list[str] = field(default_factory=list)
    chunk_indexes: list[int] = field(default_factory=list)
    pages: list[int] = field(default_factory=list)


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_text(text: str) -> str:
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def evidence_score(evidence: str, text: str) -> float:
    """Share of the quote found as one unbroken run in the text (1.0 = word for word).
    Punctuation and case are ignored: models often change a comma, which is fine."""
    ev, tx = normalize_text(evidence), normalize_text(text)
    if not ev:
        return 0.0
    if ev in tx:
        return 1.0
    match = difflib.SequenceMatcher(None, tx, ev, autojunk=False).find_longest_match(0, len(tx), 0, len(ev))
    return match.size / len(ev)


def _canonical(name: str, canonical: dict[str, str]) -> tuple[str, str, str | None]:
    """-> (display name, key, acronym alias). Known names win, so spelling stays consistent."""
    name = clean_name(name)
    long, short = split_acronym(name)
    key = concept_key(long)
    return canonical.get(key, long), key, short


def clean_extraction(
    result: ConceptExtraction, part: SectionPart, canonical: dict[str, str], min_evidence: float = 0.8
) -> tuple[list[Found], list[str]]:
    """Returns (concepts kept, reasons for the ones dropped)."""
    kept: dict[str, Found] = {}
    dropped: list[str] = []
    for c in result.concepts[:MAX_CONCEPTS_PER_PART]:
        name, key, alias = _canonical(c.name, canonical)
        if not key or len(name.split()) > MAX_NAME_WORDS:
            dropped.append(f"bad name: {c.name!r}")
            continue
        if evidence_score(c.evidence, part.text) < min_evidence:
            # The quote is not in the text: the concept probably came from the model's
            # general knowledge, not from this file. Not grounded -> not in the graph.
            dropped.append(f"evidence not in text: {name}")
            continue
        prereqs: dict[str, str] = {}
        for p in c.prerequisites:
            p_name, p_key, _ = _canonical(p, canonical)
            if p_key and p_key != key and len(p_name.split()) <= MAX_NAME_WORDS:
                prereqs.setdefault(p_key, p_name)
        chunk_indexes = [i for i, _, t in part.chunks if evidence_score(c.evidence, t) >= min_evidence]
        if not chunk_indexes:  # quote spans two chunks
            chunk_indexes = [i for i, _, _ in part.chunks]
        pages = sorted({p for i, p, _ in part.chunks if i in chunk_indexes and p is not None})
        if key in kept:  # the model listed the same concept twice
            kept[key].prerequisites += [n for n in prereqs.values() if n not in kept[key].prerequisites]
            continue
        kept[key] = Found(
            name=name,
            key=key,
            definition=clean_name(c.definition, 500),
            prerequisites=list(prereqs.values())[:MAX_PREREQUISITES],
            evidence=clean_name(c.evidence, 300),
            section=part.section,
            aliases=[alias] if alias else [],
            chunk_indexes=chunk_indexes,
            pages=pages,
        )
    return list(kept.values()), dropped


def merge_found(found: list[Found]) -> dict[str, Found]:
    """The same concept from two sections of one file -> one entry (first definition wins)."""
    out: dict[str, Found] = {}
    for f in found:
        if f.key not in out:
            out[f.key] = f
            continue
        m = out[f.key]
        m.prerequisites += [p for p in f.prerequisites if p not in m.prerequisites]
        m.aliases += [a for a in f.aliases if a not in m.aliases]
        m.chunk_indexes = sorted(set(m.chunk_indexes + f.chunk_indexes))
        m.pages = sorted(set(m.pages + f.pages))
    return out


# ---------------------------------------------------------------------------
# 4. Running it for one document
# ---------------------------------------------------------------------------


GRAPH_DOWN = "The concept graph database (Neo4j) is not reachable. Start it with docker compose and retry."


async def extract_document(document_id: int) -> None:
    """Extract concepts for one ready document. Safe to call again (re-extraction)."""
    async with SessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None or doc.superseded_at is not None or doc.status != DocumentStatus.ready:
            return
        if not get_settings().concept_extraction:
            doc.concepts_status = "off"
            await session.commit()
            return
        uploader = await session.get(User, doc.uploaded_by)
        try:
            with trace("extract_concepts", uploader, "concepts", input={"file": doc.file_name}) as root:
                stats = await _run(session, doc, uploader)
                root.update(output=stats)
        except Exception as exc:  # noqa: BLE001 - every failure must end in a visible status
            await session.rollback()
            doc = await session.get(Document, document_id)
            if isinstance(exc, (ServiceUnavailable, OSError)):
                doc.concepts_error = GRAPH_DOWN
            elif isinstance(exc, LLMError):
                doc.concepts_error = exc.user_message
            else:
                log.exception("Concept extraction failed for document %s", document_id)
                kind = "Neo4j error" if isinstance(exc, Neo4jError) else "Unexpected error"
                doc.concepts_error = f"{kind}: {type(exc).__name__}: {exc}"[:500]
            doc.concepts_status = "failed"
            await session.commit()


async def _run(session: AsyncSession, doc: Document, uploader: User | None) -> dict:
    s = get_settings()
    doc.concepts_status = "extracting"
    doc.concepts_error = None
    await session.commit()

    course = await session.get(Course, doc.course_id)
    module = await session.get(Module, doc.module_id)
    chunks = (await session.scalars(select(Chunk).where(Chunk.document_id == doc.id))).all()
    parts = build_parts(list(chunks), s.concept_max_section_chars)

    # Names the model should reuse: this course's concepts + the LMS topic catalogue
    # (which also covers prerequisites from other courses, e.g. "Linear Regression").
    known = await store.course_concepts(course.id)
    topic_names = (await session.scalars(select(Topic.name))).all()
    canonical = {concept_key(n): n for n in topic_names}
    canonical.update({k.key: k.name for k in known if k.status != "rejected"})
    known_list = format_known(list(canonical.values()))

    # 1. One LLM call per section part
    found: list[Found] = []
    cost, dropped = 0.0, []
    for part in parts:
        with observe("extract_section", input={"section": part.section, "chars": len(part.text)}) as span:
            messages = [
                SystemMessage(EXTRACT_SYSTEM),
                HumanMessage(
                    EXTRACT_USER.format(
                        course=course.title,
                        module=module.title,
                        section=part.section or "(no heading)",
                        known=known_list,
                        text=part.text,
                    )
                ),
            ]
            parsed, result = await chat_structured(
                session,
                messages=messages,
                schema=ConceptExtraction,
                feature="extract_concepts",
                user=uploader,
                max_tokens=s.concept_max_output_tokens,
            )
            cost += result.cost_usd
            items, why = clean_extraction(parsed, part, canonical)
            found += items
            dropped += why
            span.update(output={"kept": [f.name for f in items], "dropped": why})
    concepts = merge_found(found)

    # 2. Prerequisites that this file doesn't explain still need a node ("mentioned only")
    names = {k: f.name for k, f in concepts.items()}
    for f in concepts.values():
        for p in f.prerequisites:
            names.setdefault(concept_key(p), p)

    # 3. Dedupe against the course graph: embed only the names that had no exact match
    by_key = key_index(known)
    new_keys = [k for k in names if k not in by_key]
    vectors: dict[str, list[float]] = {}
    if new_keys:
        texts = [f"{names[k]}: {concepts[k].definition}" if k in concepts else names[k] for k in new_keys]
        embedded = await embed_texts(session, texts, feature="embed_concepts", user=uploader)
        vectors = dict(zip(new_keys, embedded.vectors, strict=True))
        cost += embedded.cost_usd
    decisions = resolve(
        course.id,
        list(names),
        vectors,
        known,
        merge_threshold=s.concept_merge_threshold,
        suggest_threshold=s.concept_suggest_threshold,
    )

    # 4. Write: nodes, "explained in this file" links, prerequisite edges
    known_by_uid = {k.uid: k for k in known}
    nodes: dict[str, store.NodeWrite] = {}
    for key, name in names.items():
        d = decisions[key]
        if d.action == "rejected":
            continue  # the teacher said no; don't bring it back
        f = concepts.get(key)
        node = nodes.get(d.uid)  # two keys merged into one node
        if node is None:
            target = known_by_uid.get(d.uid)
            node = nodes[d.uid] = store.NodeWrite(
                uid=d.uid,
                key=target.key if target else key,
                name=target.name if target else name,
                definition=f.definition if f else None,
                embedding=vectors.get(key) if d.action == "new" else None,
                possible_duplicate_of=d.possible_duplicate_of,
            )
        if d.action == "merged":
            node.aliases.append(name)
        if f:
            node.aliases += f.aliases
            node.definition = node.definition or f.definition
            node.explained = store.Explained(f.section, f.chunk_indexes, f.pages, f.evidence)
    edges = set()
    for key, f in concepts.items():
        a = decisions[key]
        for p in f.prerequisites:
            b = decisions[concept_key(p)]
            if "rejected" not in (a.action, b.action) and a.uid != b.uid:
                edges.add((a.uid, b.uid))

    doc_meta = store.DocMeta(doc.id, course.id, module.id, doc.file_name)
    written = await store.write_document(doc_meta, list(nodes.values()), sorted(edges))

    doc.num_concepts = sum(1 for n in nodes.values() if n.explained)
    doc.concepts_cost_usd = round(cost, 6)
    doc.concepts_status = "done"
    await session.commit()
    if doc.replaces_id:  # the new version's concepts are in; the old version's links go
        await store.remove_document(doc.replaces_id, course.id)

    stats = {
        "sections": len(parts),
        "concepts": doc.num_concepts,
        "mentioned_only": sum(1 for n in nodes.values() if not n.explained),
        "dropped": dropped,
        "merged": [k for k, d in decisions.items() if d.action == "merged"],
        "possible_duplicates": [k for k, d in decisions.items() if d.possible_duplicate_of],
        **written,
        "cost_usd": doc.concepts_cost_usd,
    }
    log.info("Concepts for %s: %s", doc.file_name, stats)
    return stats
