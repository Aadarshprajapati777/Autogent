"""Embedding service for semantic memory search.

Uses fastembed (ONNX-based, runs locally without GPU) to generate dense
vector embeddings. Embeddings are stored in PostgreSQL via the pgvector
extension and searched using cosine similarity.

The model is loaded lazily on first use — the first call downloads the
ONNX model (~100MB) and caches it locally. Subsequent calls are fast.
"""
from __future__ import annotations

import logging
from typing import Sequence

log = logging.getLogger(__name__)

# Model: all-MiniLM-L6-v2 — 384 dimensions, fast, good quality for short text.
# This is the standard choice for semantic search over facts and messages.
_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_EMBEDDING_DIM = 384

_model = None
_model_loading = False


def _get_model():
    """Lazily load the fastembed model. Thread-safe via a simple flag."""
    global _model, _model_loading
    if _model is not None:
        return _model
    if _model_loading:
        # Another call is loading — wait for it
        import time
        while _model_loading and _model is None:
            time.sleep(0.5)
        return _model
    _model_loading = True
    try:
        from fastembed import TextEmbedding
        _model = TextEmbedding(model_name=_MODEL_NAME)
        log.info("fastembed model loaded: %s (dim=%d)", _MODEL_NAME, _EMBEDDING_DIM)
    except Exception as exc:
        log.error("Failed to load fastembed model: %s", exc)
        raise
    finally:
        _model_loading = False
    return _model


def embed_text(text: str) -> list[float]:
    """Generate a dense embedding for a single text string.
    Returns a list of floats (384 dimensions)."""
    model = _get_model()
    embeddings = list(model.embed([text]))
    if not embeddings:
        return []
    return embeddings[0].tolist()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for multiple texts in a single batch.
    More efficient than calling embed_text repeatedly."""
    if not texts:
        return []
    model = _get_model()
    embeddings = list(model.embed(texts))
    return [e.tolist() for e in embeddings]


def embedding_dim() -> int:
    """Return the dimensionality of the embeddings."""
    return _EMBEDDING_DIM
