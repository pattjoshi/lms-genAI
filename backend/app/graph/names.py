"""Concept names -> one canonical key, so "Activation Functions", "activation function" and
"Activation function." end up as ONE node in the graph.

This is the cheap, rule-based half of entity deduplication (also called entity
resolution). Spelling variants are handled here, for free and deterministically.
Synonyms ("Backprop" / "Backpropagation") need meaning, so they are handled with
embeddings in `app.graph.resolve`.
"""

import re

_SPACES = re.compile(r"\s+")
_NOT_WORD = re.compile(r"[^a-z0-9+#]+")  # keep C++ / C# intact
_ACRONYM = re.compile(r"^(?P<long>.+?)\s*\((?P<short>[A-Za-z][A-Za-z0-9\-]{1,9})\)$")
# Words that end in "s" but are not plurals.
_NO_SINGULAR = {"analysis", "basis", "axis", "loss", "class", "less", "process", "access", "bias", "pandas", "numpy"}


def clean_name(name: str, max_chars: int = 80) -> str:
    """Display form: trimmed, single spaces, no trailing full stop."""
    return _SPACES.sub(" ", name).strip().rstrip(".:;,").strip()[:max_chars]


def split_acronym(name: str) -> tuple[str, str | None]:
    """'Rectified Linear Unit (ReLU)' -> ('Rectified Linear Unit', 'ReLU')."""
    m = _ACRONYM.match(name)
    return (m.group("long").strip(), m.group("short")) if m else (name, None)


def _singular(word: str) -> str:
    if word in _NO_SINGULAR or len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("ches", "shes", "sses", "xes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def concept_key(name: str) -> str:
    """Canonical key: lower case, punctuation removed, words singular, leading article dropped."""
    long, _ = split_acronym(clean_name(name))
    words = _NOT_WORD.sub(" ", long.lower()).split()
    if words and words[0] in ("the", "a", "an") and len(words) > 1:
        words = words[1:]
    return " ".join(_singular(w) for w in words)
