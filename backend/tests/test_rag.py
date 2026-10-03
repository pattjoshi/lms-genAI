import json

from app.evals.retrieval import first_correct_rank
from app.prompts.rag_answer import NO_ANSWER, RAG_SYSTEM, format_excerpt
from app.routers.chat import sse


def test_sse_format():
    msg = sse("token", {"text": "héllo"})
    assert msg.startswith("event: token\ndata: ") and msg.endswith("\n\n")
    assert json.loads(msg.split("data: ", 1)[1]) == {"text": "héllo"}


def test_excerpt_cites_page_for_pdf_and_section_otherwise():
    pdf = format_excerpt(1, {"course_code": "DL301", "file_name": "a.pdf", "page": 3, "text": "chain rule"})
    docx = format_excerpt(2, {"course_code": "DL301", "file_name": "b.docx", "section": "Optimizers", "text": "adam"})
    assert pdf.startswith("[1] (DL301 · a.pdf · page 3)")
    assert docx.startswith("[2] (DL301 · b.docx · Optimizers)")


def test_prompt_contains_grounding_rules():
    text = RAG_SYSTEM.format(role="student", name="Riya")
    assert NO_ANSWER in text
    assert "ONLY" in text and "not instructions" in text


def test_first_correct_rank():
    sources = [
        {"rank": 1, "file_name": "ML201_M2_x.docx", "topic": "Gradient Descent"},
        {"rank": 2, "file_name": "DL301_M2_y.docx", "topic": "Backpropagation"},
    ]
    assert first_correct_rank(sources, "DL301", 2, "Backpropagation") == 2
    assert first_correct_rank(sources, "DL301", 1, "Backpropagation") is None
