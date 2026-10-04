"""Shapes shared by both AI providers."""

import base64
from dataclasses import dataclass, field


@dataclass
class AIResult:
    """An answer from the AI, in the same shape whichever provider gave it."""

    text: str
    provider: str
    model: str
    web_search_used: bool = False
    web_searches: int = 0
    sources: list[dict] = field(default_factory=list)  # [{"title": ..., "url": ...}]
    notes: list[str] = field(default_factory=list)  # things the user should know


_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def image_data_url(image: bytes) -> str:
    """Turn image bytes into the data: URL form both providers accept."""
    mime = next((mime for start, mime in _IMAGE_SIGNATURES if image.startswith(start)), None)
    if mime is None and image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        mime = "image/webp"
    if mime is None:
        raise ValueError("Unsupported image type. Use a PNG, JPEG, GIF, or WebP file.")
    return f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"
