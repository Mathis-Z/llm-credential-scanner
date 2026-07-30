# Deterministic chunking + local-embedding retrieval used by CredSearcher's RAG pipeline.

import logging
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer

from scanner.settings import get_settings

logger = logging.getLogger('scanner.rag')


@dataclass
class Chunk:
    text: str
    source_url: str


@lru_cache(maxsize=1)
def _get_embedding_model() -> SentenceTransformer:
    """Lazily load and cache the embedding model for the process (first call may download it)."""
    settings = get_settings()
    logger.debug("Loading embedding model %s", settings.embedding_model_name)
    return SentenceTransformer(settings.embedding_model_name)


def chunk_pages(pages: list[tuple[str, str]], chunk_size: int, chunk_overlap: int) -> list[Chunk]:
    """Split (source_url, markdown_content) pages into overlapping chunks, skipping empty pages."""
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks: list[Chunk] = []
    for url, content in pages:
        if not content or not content.strip():
            continue
        for piece in splitter.split_text(content):
            piece = piece.strip()
            if piece:
                chunks.append(Chunk(text=piece, source_url=url))
    return chunks


def retrieve_top_chunks(query: str, chunks: list[Chunk], top_k: int) -> list[Chunk]:
    """Embed query + chunks, rank by cosine similarity, return top_k. Returns [] on embedding failure."""
    if not chunks:
        return []
    try:
        model = _get_embedding_model()
        chunk_embeddings = np.asarray(model.encode([c.text for c in chunks], normalize_embeddings=True))
        query_embedding = np.asarray(model.encode([query], normalize_embeddings=True))[0]
    except Exception:
        logger.exception("Embedding failed; skipping retrieval")
        return []

    similarities = chunk_embeddings @ query_embedding  # normalized vectors -> dot product == cosine similarity
    ranked_indices = np.argsort(-similarities)[:top_k]
    return [chunks[i] for i in ranked_indices]
