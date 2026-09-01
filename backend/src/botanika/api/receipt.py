"""In-memory, crop-only receipt handling for connectivity validation."""

from __future__ import annotations

import asyncio
import hashlib
import time
import warnings
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from PIL import Image

from botanika.core.settings import Settings


@dataclass(frozen=True)
class Receipt:
    request_id: str
    accepted: bool
    width: int
    height: int
    mime_type: str
    byte_count: int
    received_at: str
    content_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "accepted": self.accepted,
            "width": self.width,
            "height": self.height,
            "mime_type": self.mime_type,
            "byte_count": self.byte_count,
            "received_at": self.received_at,
            "content_hash": self.content_hash,
        }


class ReceiptValidationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DuplicateRequestError(Exception):
    """The same idempotency key was used with different bytes."""


class ReceiptStore:
    """Receipt cache with no image persistence.

    The raw upload is held only by the request and Pillow while it is decoded.
    The cache stores the compact receipt and raw content hash for bounded retry
    deduplication; it never stores image bytes.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._records: OrderedDict[str, tuple[float, Receipt]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def receive(self, request_id: str, data: bytes, declared_mime: str) -> Receipt:
        content_hash = hashlib.sha256(data).hexdigest()
        async with self._lock:
            self._evict_expired()
            existing = self._records.get(request_id)
            if existing is not None:
                _, receipt = existing
                normalized_mime = (declared_mime or "").split(";", 1)[0].strip().lower()
                if receipt.content_hash != content_hash or receipt.mime_type != normalized_mime:
                    raise DuplicateRequestError(
                        "idempotency key was already used for different image content"
                    )
                self._records.move_to_end(request_id)
                return receipt

            width, height, mime_type = _decode_and_validate(
                data,
                declared_mime,
                max_pixels=self.settings.max_image_pixels,
                max_dimension=self.settings.max_image_dimension,
            )
            received_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            receipt = Receipt(
                request_id=request_id,
                accepted=True,
                width=width,
                height=height,
                mime_type=mime_type,
                byte_count=len(data),
                received_at=received_at,
                content_hash=content_hash,
            )
            self._records[request_id] = (time.monotonic(), receipt)
            self._records.move_to_end(request_id)
            while len(self._records) > self.settings.idempotency_cache_size:
                self._records.popitem(last=False)
            return receipt

    def _evict_expired(self) -> None:
        cutoff = time.monotonic() - self.settings.idempotency_ttl_seconds
        while self._records:
            first_key, (created, _) = next(iter(self._records.items()))
            if created >= cutoff:
                break
            del self._records[first_key]

    def cached_count(self) -> int:
        self._evict_expired()
        return len(self._records)


def _decode_and_validate(
    data: bytes,
    declared_mime: str | None,
    *,
    max_pixels: int,
    max_dimension: int,
) -> tuple[int, int, str]:
    if not declared_mime:
        raise ReceiptValidationError("mime_required", "image MIME type is required")
    mime = declared_mime.split(";", 1)[0].strip().lower()
    if mime not in {"image/jpeg", "image/webp"}:
        raise ReceiptValidationError(
            "unsupported_format", "only JPEG and WebP images are accepted"
        )
    if len(data) == 0:
        raise ReceiptValidationError("empty_image", "image body is empty")

    if mime == "image/jpeg":
        magic_matches = data[:3] == b"\xff\xd8\xff"
        expected_format = "JPEG"
    else:
        magic_matches = len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
        expected_format = "WEBP"
    if not magic_matches:
        raise ReceiptValidationError(
            "magic_mismatch", "declared MIME type does not match image magic bytes"
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format != expected_format:
                    raise ReceiptValidationError(
                        "format_mismatch", "image decoder format does not match declaration"
                    )
                width, height = image.size
                if width <= 0 or height <= 0:
                    raise ReceiptValidationError("invalid_dimensions", "image dimensions are invalid")
                if width > max_dimension or height > max_dimension:
                    raise ReceiptValidationError("dimensions_too_large", "image dimensions exceed the limit")
                if width * height > max_pixels:
                    raise ReceiptValidationError("pixels_too_many", "decoded pixel count exceeds the limit")
                if getattr(image, "n_frames", 1) != 1:
                    raise ReceiptValidationError("animated_image", "animated images are not accepted")
                image.verify()

            # verify() does not fully decode every pixel. Reopen and load to
            # catch truncated or malformed compressed image data.
            with Image.open(BytesIO(data)) as image:
                image.load()
    except ReceiptValidationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ReceiptValidationError("pixels_too_many", "decoded pixel count exceeds the limit") from exc
    except Exception as exc:
        raise ReceiptValidationError("invalid_image", "image could not be decoded") from exc

    return width, height, mime
