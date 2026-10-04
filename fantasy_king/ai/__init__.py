"""The AI connection: one shared function, two providers.

The rest of the app calls ask_ai() and never needs to know which provider
answered. AI_PROVIDER in .env picks ChatGPT plan usage or OpenRouter.
"""

from fantasy_king.ai.client import ask_ai
from fantasy_king.ai.errors import AIError
from fantasy_king.ai.types import AIResult

__all__ = ["AIError", "AIResult", "ask_ai"]
