"""BM25 keyword vectors ("sparse vectors") for hybrid search.

Why: embeddings (dense vectors) match MEANING, so "why does my model memorise the
training data" finds the overfitting notes. But they are weak on exact tokens such as
`pd.merge`, `__init__`, `RLHF` or `EXPLAIN ANALYZE`: rare words a student copies from
an error message or the slides. Keyword search is strong exactly there.

How BM25 becomes a vector:
- Every token gets a fixed id (a hash), so a text becomes {token_id: weight} with only
  a few non-zero entries out of 2^32 possible ids. That is a "sparse" vector.
- Document weight = BM25 term-frequency part:  tf * (k1 + 1) / (tf + k1 * (1 - b + b * len / avg_len))
  More repeats count, but with diminishing returns (k1), and long chunks are penalised (b).
- The IDF part (rare words matter more) is computed by Qdrant at query time over the
  whole collection (`Modifier.IDF`), so adding documents never requires re-weighting.
- Query weight = 1 per distinct token.

This is the same scheme as fastembed's "Qdrant/bm25" model, written out here so every
step is visible (and it needs no model download).
"""

import re
import zlib
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from py_rust_stemmers import SnowballStemmer

K1 = 1.2  # term-frequency saturation
B = 0.75  # length normalisation
AVG_DOC_TOKENS = 100  # a ~1000-character chunk has ~100 tokens left after removing stop words

# Words so common they say nothing about the topic.
STOPWORDS = frozenset(
    """a about above after again all also am an and any are as at be because been before being below between
    both but by can could did do does doing down during each few for from further had has have having he her
    here hers him his how i if in into is it its itself just me more most my no nor not now of off on once only
    or other our out over own same she should so some such than that the their them then there these they this
    those through to too under until up very was we were what when where which while who whom why will with
    would you your yours""".split()
)

# Lower-case words; keeps inner dots, dashes and underscores so `pd.merge`, `k-means`,
# `read_csv` and `__init__` stay single tokens (their parts are added separately too).
TOKEN_RE = re.compile(r"[a-z0-9_]+(?:[.\-][a-z0-9_]+)*")


@lru_cache(maxsize=1)
def _stemmer() -> SnowballStemmer:
    return SnowballStemmer("english")


def tokenize(text: str) -> list[str]:
    """'Using pd.merge for JOINS' -> ['use', 'pd.merge', 'pd', 'merg', 'join']"""
    stem = _stemmer().stem_word
    out: list[str] = []
    for match in TOKEN_RE.findall(text.lower()):
        parts = re.split(r"[.\-]", match)
        candidates = [match, *parts] if len(parts) > 1 else [match]
        for token in candidates:
            if len(token) < 2 or token in STOPWORDS:
                continue
            # Stem plain words only ("joins" -> "join"); leave code such as `__init__` alone.
            out.append(stem(token) if token.isalpha() else token)
    return out


def token_id(token: str) -> int:
    """Stable id for a token. Python's hash() changes between runs, so it can't be used."""
    return zlib.crc32(token.encode("utf-8"))


@dataclass
class SparseVector:
    indices: list[int]
    values: list[float]

    def __bool__(self) -> bool:
        return bool(self.indices)


def _to_vector(weights: dict[int, float]) -> SparseVector:
    items = sorted(weights.items())
    return SparseVector([i for i, _ in items], [round(v, 6) for _, v in items])


def encode_document(text: str) -> SparseVector:
    tokens = tokenize(text)
    length_norm = 1 - B + B * len(tokens) / AVG_DOC_TOKENS
    weights: dict[int, float] = {}
    for token, tf in Counter(tokens).items():
        idx = token_id(token)
        # Two tokens with the same hash (very rare) share one slot instead of breaking the vector.
        weights[idx] = weights.get(idx, 0.0) + tf * (K1 + 1) / (tf + K1 * length_norm)
    return _to_vector(weights)


def encode_query(text: str) -> SparseVector:
    return _to_vector({token_id(t): 1.0 for t in set(tokenize(text))})
