"""Parsing, chunking and tagging on the real sample files. No network, no database."""

from pathlib import Path

import pytest

from app.config import REPO_ROOT
from app.ingest.chunker import ChunkDraft, chunk_sections
from app.ingest.parsers import ParseError, Section, file_type_for, parse_file, strip_repeated_lines
from app.ingest.tagger import fill_missing_headings, tag_chunk
from app.seed.catalog import COURSES

SAMPLES = REPO_ROOT / "data" / "course_files"


def sample(prefix: str) -> Path:
    return next(SAMPLES.glob(f"{prefix}*"))


def test_every_sample_file_parses_and_chunks():
    files = sorted(SAMPLES.iterdir())
    assert len(files) == 24
    assert {f.suffix for f in files} == {".pdf", ".docx", ".html", ".txt"}
    for f in files:
        chunks = chunk_sections(parse_file(f, file_type_for(f.name)), 1000, 150)
        assert chunks, f.name
        assert all(len(c.text) <= 1000 + 60 for c in chunks), f.name  # +heading prefix


def test_pdf_keeps_page_numbers_and_strips_footer():
    sections = parse_file(sample("DL301_M1"), "pdf")
    assert [s.page for s in sections] == [1, 2, 3]
    assert sections[2].text.startswith("Chain Rule")  # each topic starts a page
    assert "Page 3" not in sections[2].text
    assert "DL301 - Neural Network Basics" not in sections[2].text


def test_docx_html_txt_keep_headings():
    for prefix, ext in [("DL301_M2", "docx"), ("DL301_M3", "html"), ("DL301_M4", "txt")]:
        headings = {s.heading for s in parse_file(sample(prefix), ext)}
        module = COURSES[2]["modules"][int(prefix[-1]) - 1]
        assert {t for t, _ in module[1]} <= headings, prefix


def test_strip_repeated_lines():
    pages = ["Header X\nreal text one\nPage 1", "Header X\nreal text two\nPage 2", "Header X\nthree\nPage 3"]
    assert strip_repeated_lines(pages) == ["real text one", "real text two", "three"]


def test_rejects_doc_and_unknown_types():
    with pytest.raises(ParseError, match=r"\.docx"):
        file_type_for("notes.doc")
    with pytest.raises(ParseError):
        file_type_for("slides.pptx")
    assert file_type_for("Notes.HTM") == "html"


def test_chunks_never_cross_pages_and_overlap():
    long_text = " ".join(f"Sentence number {i} explains something." for i in range(200))
    sections = [Section(long_text, page=1), Section("Second page text that is long enough.", page=2)]
    chunks = chunk_sections(sections, chunk_size=300, chunk_overlap=60)
    assert {c.page for c in chunks} == {1, 2}
    page1 = [c.text for c in chunks if c.page == 1]
    # overlap: the end of one chunk reappears at the start of the next
    assert any(page1[i][-30:].split()[-1] in page1[i + 1][:80] for i in range(len(page1) - 1))


def test_fill_missing_headings_carries_forward():
    drafts = [
        ChunkDraft(0, "Module intro text\nPerceptron\nThe perceptron is...", 1, None),
        ChunkDraft(1, "more about perceptrons", 1, None),
        ChunkDraft(2, "Activation Functions\nSigmoid and ReLU", 2, None),
    ]
    fill_missing_headings(drafts, ["Perceptron", "Activation Functions"])
    assert [d.section for d in drafts] == ["Perceptron", "Perceptron", "Activation Functions"]


def test_tag_chunk_heading_rule_then_embeddings():
    topics = [("Pooling", "medium"), ("Convolution", "hard")]
    vectors = [[1.0, 0.0], [0.0, 1.0]]
    assert tag_chunk("Convolution", [1.0, 0.0], topics, vectors).score == 1.0  # rule wins
    tag = tag_chunk(None, [0.1, 0.9], topics, vectors)
    assert (tag.topic, tag.difficulty) == ("Convolution", "hard")
