"""Phase 3 concept extraction, each step on its own. No Neo4j, OpenAI or Postgres needed."""

from app.graph.extract import (
    ConceptExtraction,
    ExtractedConcept,
    Found,
    SectionPart,
    build_parts,
    clean_extraction,
    evidence_score,
    join_overlapping,
    merge_found,
)
from app.graph.names import clean_name, concept_key, split_acronym
from app.graph.resolve import Known, resolve
from app.models import Chunk
from app.prompts.extract_concepts import format_known

# ---------- Names -> keys ----------


def test_spelling_variants_share_one_key():
    assert concept_key("Activation Functions") == concept_key("activation function.") == "activation function"
    assert concept_key("The Chain Rule") == concept_key("chain rule")
    assert concept_key("Binary Trees") == concept_key("binary tree")
    assert concept_key("Dictionaries and Sets") == "dictionary and set"


def test_keys_keep_meaningful_endings_and_symbols():
    assert concept_key("Bias") == "bias"  # not "bia"
    assert concept_key("Principal Component Analysis") == "principal component analysis"
    assert concept_key("Pandas Basics") == "pandas basic"
    assert concept_key("C++") == "c++"
    assert concept_key("Big-O Notation") == "big o notation"


def test_acronym_becomes_an_alias():
    assert split_acronym("Rectified Linear Unit (ReLU)") == ("Rectified Linear Unit", "ReLU")
    assert split_acronym("Chain Rule") == ("Chain Rule", None)
    assert concept_key("Rectified Linear Unit (ReLU)") == concept_key("rectified linear unit")
    assert clean_name("  Chain   Rule. ") == "Chain Rule"


def test_known_names_are_listed_once_and_sorted():
    assert format_known([]) == "(none yet)"
    assert format_known(["Recursion", "Arrays", "Recursion"]) == "- Arrays\n- Recursion"


# ---------- Sections ----------


def _chunk(i, text, section, page=None):
    return Chunk(chunk_index=i, text=f"{section}\n{text}" if section else text, section=section, page=page)


def test_overlapping_chunks_are_glued_without_repeating_text():
    a = "The chain rule multiplies local derivatives along the path."
    b = "local derivatives along the path. This is backpropagation."
    glued = "The chain rule multiplies local derivatives along the path. This is backpropagation."
    assert join_overlapping(a, b) == glued
    assert join_overlapping("no overlap here.", "Another sentence.") == "no overlap here.\nAnother sentence."


def test_parts_follow_headings_and_respect_the_size_limit():
    chunks = [
        _chunk(0, "Perceptron text one.", "Perceptron", page=1),
        _chunk(1, "Perceptron text two.", "Perceptron", page=2),
        _chunk(2, "Chain rule text.", "Chain Rule", page=3),
    ]
    parts = build_parts(chunks, max_chars=10_000)
    assert [p.section for p in parts] == ["Perceptron", "Chain Rule"]
    assert parts[0].text == "Perceptron text one.\nPerceptron text two."  # heading prefix removed
    assert [i for i, _, _ in parts[0].chunks] == [0, 1]
    small = build_parts(chunks, max_chars=25)
    assert [p.section for p in small] == ["Perceptron", "Perceptron", "Chain Rule"]


# ---------- Validation ----------

TEXT = (
    "Prerequisites: Derivatives. The chain rule tells us how to differentiate a function composed of other "
    "functions. Applying the chain rule systematically from the output back to the input is exactly the "
    "backpropagation algorithm."
)
PART = SectionPart(section="Chain Rule", text=TEXT, chunks=[(4, 7, TEXT)])


def _c(name, prereqs=(), evidence="The chain rule tells us how to differentiate", definition="A rule."):
    return ExtractedConcept(name=name, definition=definition, prerequisites=list(prereqs), evidence=evidence)


def test_evidence_must_be_in_the_text():
    assert evidence_score("the chain rule tells us how to differentiate", TEXT) == 1.0  # case/punctuation ignored
    assert evidence_score("The chain rule, tells us how to differentiate!", TEXT) == 1.0
    assert evidence_score("Neural networks were invented in 1943 by McCulloch", TEXT) < 0.5


def test_clean_extraction_drops_ungrounded_concepts_and_fixes_names():
    result = ConceptExtraction(
        concepts=[
            _c("chain rule.", prereqs=["derivatives", "Chain Rule", "Derivatives"]),
            _c("Backpropagation", prereqs=["Chain Rule"], evidence="is exactly the backpropagation algorithm"),
            _c("Gradient Vanishing", evidence="Sigmoid saturates for large inputs and kills gradients"),
            _c("Chain Rule", prereqs=["Functions"]),  # listed twice
        ]
    )
    canonical = {"chain rule": "Chain Rule", "derivative": "Derivatives"}
    kept, dropped = clean_extraction(result, PART, canonical)
    by_name = {f.name: f for f in kept}
    assert set(by_name) == {"Chain Rule", "Backpropagation"}  # canonical spelling; duplicate merged
    assert by_name["Chain Rule"].prerequisites == ["Derivatives", "Functions"]  # no self, no dupes
    assert by_name["Chain Rule"].chunk_indexes == [4] and by_name["Chain Rule"].pages == [7]
    assert dropped == ["evidence not in text: Gradient Vanishing"]


def test_merge_found_unions_one_concept_from_two_sections():
    a = Found("Recursion", "recursion", "A function calling itself.", ["Functions"], "q", "S1", [], [1], [2])
    b = Found("Recursion", "recursion", "Other words.", ["Stacks", "Functions"], "q2", "S2", ["Rec"], [5], [3])
    merged = merge_found([a, b])["recursion"]
    assert merged.definition == "A function calling itself."  # first one wins
    assert merged.prerequisites == ["Functions", "Stacks"]
    assert merged.chunk_indexes == [1, 5] and merged.pages == [2, 3] and merged.aliases == ["Rec"]


# ---------- Entity resolution ----------


def test_resolve_uses_keys_aliases_and_two_similarity_thresholds():
    known = [
        Known("7:backpropagation", "backpropagation", "Backpropagation", "draft", ["Backprop"], [1.0, 0.0, 0.0]),
        Known("7:dropout", "dropout", "Dropout", "rejected", [], [0.0, 1.0, 0.0]),
    ]
    vectors = {
        "backward pass": [0.99, 0.05, 0.0],  # ~synonym of backpropagation -> merge
        "weight decay": [0.0, 0.0, 1.0],  # unrelated -> new
        "drop connect": [0.1, 0.9, 0.4],  # close to the rejected Dropout, but in the grey zone
    }
    out = resolve(
        7,
        ["backprop", "backward pass", "weight decay", "drop connect", "dropout"],
        vectors,
        known,
        merge_threshold=0.95,
        suggest_threshold=0.85,
    )
    assert out["backprop"].action == "existing" and out["backprop"].uid == "7:backpropagation"  # alias
    assert out["backward pass"].action == "merged" and out["backward pass"].uid == "7:backpropagation"
    assert out["weight decay"].action == "new" and out["weight decay"].uid == "7:weight decay"
    assert out["weight decay"].possible_duplicate_of is None
    assert out["drop connect"].action == "new" and out["drop connect"].possible_duplicate_of == "7:dropout"
    assert out["dropout"].action == "rejected"  # the teacher said no: never re-created


def test_synonyms_inside_one_file_become_one_node():
    vectors = {"gradient descent": [1.0, 0.0], "steepest descent": [0.98, 0.1]}
    out = resolve(1, list(vectors), vectors, [], merge_threshold=0.9, suggest_threshold=0.8)
    assert out["gradient descent"].action == "new"
    assert out["steepest descent"].action == "merged" and out["steepest descent"].uid == "1:gradient descent"
