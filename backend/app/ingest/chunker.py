"""Step 2: split sections into chunks small enough to embed and retrieve precisely.

Strategy: recursive character splitting INSIDE each section (never across a page or
heading boundary), so every chunk has exactly one page/heading for its citation.
The splitter tries paragraph breaks first, then lines, then sentences, then words, and
only cuts mid-word as a last resort.

Trade-offs to experiment with (CHUNK_SIZE / CHUNK_OVERLAP in .env):
- small chunks -> precise matches, but may lose the context needed to answer
- big chunks   -> more context, but the embedding is a blurry "average" and costs more tokens
- overlap      -> a sentence cut at a boundary still appears whole in one of the two chunks
"""

from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.ingest.parsers import Section


@dataclass
class ChunkDraft:
    index: int
    text: str
    page: int | None
    section: str | None


def chunk_sections(sections: list[Section], chunk_size: int, chunk_overlap: int) -> list[ChunkDraft]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
        keep_separator="end",  # keep the full stop with its sentence
    )
    drafts: list[ChunkDraft] = []
    for section in sections:
        for piece in splitter.split_text(section.text):
            piece = piece.strip()
            if len(piece) < 20:  # stray fragments ("-", a lone heading) aren't worth a vector
                continue
            # Prefix the heading so the chunk is understandable (and embeddable) on its own.
            text = f"{section.heading}\n{piece}" if section.heading and not piece.startswith(section.heading) else piece
            drafts.append(ChunkDraft(index=len(drafts), text=text, page=section.page, section=section.heading))
    return drafts
