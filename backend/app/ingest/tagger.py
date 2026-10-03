"""Step 4: tag each chunk with a topic (and that topic's difficulty).

Two-step approach, cheapest first:
1. Rule: if the chunk's heading IS a topic name of the module, use it (score 1.0).
2. Embeddings: otherwise pick the module topic whose embedding is most similar to the
   chunk's embedding (cosine similarity). We already have the chunk embeddings, so this
   costs only a few extra tokens for the topic names, and no LLM call.

An LLM classifier would be more flexible but costs a call per chunk. Using a rule
before a model is a good habit: cheaper, faster, deterministic.
"""

import math
from dataclasses import dataclass

from app.ingest.chunker import ChunkDraft


@dataclass
class TopicTag:
    topic: str
    difficulty: str
    score: float


def fill_missing_headings(drafts: list[ChunkDraft], topic_names: list[str]) -> None:
    """PDF text has no heading markup. Recover it in reading order:
    a line that IS a topic name starts that topic, and following chunks without a
    heading belong to it too (until the next topic line). Mutates `drafts`.
    """
    names = {n.lower(): n for n in topic_names}
    current: str | None = None
    for draft in drafts:
        if draft.section:
            current = draft.section
            continue
        found = [names[line.strip().lower()] for line in draft.text.splitlines() if line.strip().lower() in names]
        if found:
            draft.section, current = found[0], found[-1]
        else:
            draft.section = current


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def tag_chunk(
    heading: str | None,
    chunk_vector: list[float],
    topics: list[tuple[str, str]],  # (name, difficulty) of the module's topics
    topic_vectors: list[list[float]],
) -> TopicTag | None:
    if not topics:
        return None
    if heading:
        for name, difficulty in topics:
            if heading.strip().lower() == name.lower():
                return TopicTag(name, difficulty, 1.0)
    scores = [cosine(chunk_vector, tv) for tv in topic_vectors]
    best = max(range(len(topics)), key=scores.__getitem__)
    return TopicTag(topics[best][0], topics[best][1], round(scores[best], 4))
