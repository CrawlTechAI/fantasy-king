"""Check the AI connection from a terminal, without opening the dashboard.

    .venv\\Scripts\\python -m fantasy_king.ai status
    .venv\\Scripts\\python -m fantasy_king.ai models openrouter [word to search for]
    .venv\\Scripts\\python -m fantasy_king.ai models chatgpt

None of these send a question to an AI, so they use none of your plan or credits.
"""

import sys

from fantasy_king.ai import chatgpt, openrouter
from fantasy_king.ai.client import provider_status
from fantasy_king.ai.errors import PROVIDER_LABELS, AIError
from fantasy_king.config import ConfigError, load_settings


def show_status() -> None:
    settings = load_settings()
    print(f"AI provider in use: {PROVIDER_LABELS[settings.ai_provider]}")
    print(f"Status: {provider_status(settings)}")
    print(f"Web search: {'on' if settings.web_search_enabled else 'off'}")


def show_models(provider: str, search: str = "") -> None:
    if provider == "chatgpt":
        models = chatgpt.list_models()
    else:
        models = [model for model in openrouter.list_models() if model["tools"]]
        print("OpenRouter models that can use web search:")
    for model in models:
        if search.lower() in f"{model['id']} {model['name']}".lower():
            print(f"  {model['id']:<40} {model['name']:<40} {model.get('price', '')}")


def main(arguments: list[str]) -> int:
    try:
        if arguments[:1] == ["status"]:
            show_status()
        elif arguments[:1] == ["models"] and arguments[1:2] in (["chatgpt"], ["openrouter"]):
            show_models(arguments[1], " ".join(arguments[2:]))
        else:
            print(__doc__)
            return 2
    except (AIError, ConfigError) as problem:
        print(problem)
        if getattr(problem, "how_to_fix", ""):
            print(f"What to do: {problem.how_to_fix}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
