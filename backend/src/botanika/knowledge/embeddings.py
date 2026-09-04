"""Small deterministic embeddings for offline knowledge retrieval.

This is intentionally not presented as a semantic foundation model.  It is a
compact hashing index over reviewed local text that gives the offline guide a
second retrieval path when a question does not match every FTS token.  The
algorithm has no model download, no network dependency, and stable output for
the same text/version/dimension tuple.
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
from typing import Iterable


EMBEDDING_VERSION = "hashing-lexical-v1"
DEFAULT_DIMENSIONS = 256
_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def tokens(text: str) -> list[str]:
    """Return normalized terms plus adjacent bigrams for stable indexing."""

    words = [item.lower() for item in _TOKEN_RE.findall(str(text or ""))]
    return words + [f"{left}_{right}" for left, right in zip(words, words[1:])]


def embed(text: str, dimensions: int = DEFAULT_DIMENSIONS) -> tuple[float, ...]:
    """Create a normalized signed feature vector using SHA-256 buckets."""

    if dimensions <= 0:
        raise ValueError("embedding dimensions must be positive")
    vector = [0.0] * int(dimensions)
    for token in tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "little") % dimensions
        vector[bucket] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return tuple(vector)
    return tuple(value / norm for value in vector)


def pack(vector: Iterable[float]) -> bytes:
    """Pack vectors as portable little-endian float32 SQLite blobs."""

    values = tuple(float(value) for value in vector)
    return struct.pack(f"<{len(values)}f", *values)


def unpack(value: bytes, dimensions: int) -> tuple[float, ...]:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError("embedding vector is not a byte buffer")
    expected = int(dimensions) * 4
    if len(value) != expected:
        raise ValueError("embedding vector length does not match its dimensions")
    return tuple(struct.unpack(f"<{dimensions}f", bytes(value)))


def cosine(left: Iterable[float], right: Iterable[float]) -> float:
    values_left = tuple(float(value) for value in left)
    values_right = tuple(float(value) for value in right)
    if len(values_left) != len(values_right):
        raise ValueError("embedding vectors must have equal dimensions")
    return sum(a * b for a, b in zip(values_left, values_right))


def digest_text(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


__all__ = [
    "DEFAULT_DIMENSIONS",
    "EMBEDDING_VERSION",
    "cosine",
    "digest_text",
    "embed",
    "pack",
    "tokens",
    "unpack",
]
