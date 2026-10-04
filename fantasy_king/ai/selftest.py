"""Three small test calls that prove the AI connection works.

Each one is a real request to the provider chosen in .env, so each uses a
little of your ChatGPT plan or OpenRouter credits. They run only when you
click their buttons on the AI connection page.
"""

import io

from fantasy_king.ai.client import ask_ai
from fantasy_king.ai.types import AIResult

EXPECTED_REPLY = "Fantasy King is connected."
IMAGE_TEXT = "KING 42"


def plain_test(**options) -> AIResult:
    """The simplest possible call: can the AI answer at all?"""
    return ask_ai(
        "You are checking a connection. Follow the request exactly and add nothing else.",
        f"Reply with exactly: {EXPECTED_REPLY}",
        **options,
    )


def web_search_test(**options) -> AIResult:
    """Can the AI search the web? Needed later for player news."""
    return ask_ai(
        "Use web search to answer. Reply in two short sentences and name your sources.",
        "Which NFL teams play in the next Thursday night game, and on what date?",
        web_search=True,
        **options,
    )


def image_test(**options) -> AIResult:
    """Can the AI read a picture? Needed later for league screenshots."""
    return ask_ai(
        "You are checking a connection. Answer in one short sentence.",
        "What word and number are written in this image?",
        images=[make_test_image()],
        **options,
    )


def make_test_image() -> bytes:
    """A small white PNG with IMAGE_TEXT written on it."""
    from PIL import Image, ImageDraw, ImageFont  # imported here: only this test needs it

    image = Image.new("RGB", (360, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.text((30, 30), IMAGE_TEXT, fill="black", font=ImageFont.load_default(size=56))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
