"""The AI connection page: sign in, pick a model, and test that it works."""

from dataclasses import replace

import streamlit as st

from fantasy_king.ai import chatgpt, chatgpt_auth, errors, openrouter, selftest
from fantasy_king.ai.errors import (
    MANAGE_USAGE_URL,
    PROVIDER_LABELS,
    AIError,
    switch_instructions,
)
from fantasy_king.ai.token_store import TokenStore
from fantasy_king.config import AI_PROVIDERS, ConfigError, Settings, load_settings, save_model

# Wording in this file marked "OpenAI guideline" comes from
# https://developers.openai.com/siwc/ui-ux-guidelines and should not be reworded.
SIGN_IN_LABEL = "Continue with ChatGPT"  # OpenAI guideline
MANAGE_USAGE_LABEL = "Manage usage"  # OpenAI guideline

TESTS = {
    "plain": ("Test a simple question", selftest.plain_test),
    "search": ("Test web search", selftest.web_search_test),
    "image": ("Test reading an image", selftest.image_test),
}


def show_error(problem: AIError) -> None:
    if problem.kind == errors.USAGE_LIMIT and problem.provider == "chatgpt":
        # OpenAI guideline: headline, message, and "Manage usage" as the main action.
        st.error(
            "**Usage limit reached**\n\n"
            "Review your plan or this app's limit in ChatGPT settings."
        )
        st.link_button(MANAGE_USAGE_LABEL, MANAGE_USAGE_URL, type="primary")
    else:
        st.error(problem.message)
        if problem.how_to_fix:
            st.write(f"**What to do:** {problem.how_to_fix}")
    st.caption(switch_instructions(problem.provider))
    if problem.request_id:
        st.caption(f"Request ID, if you need to report this: {problem.request_id}")


def show_saved_error(key: str) -> None:
    problem = st.session_state.pop(key, None)
    if problem:
        show_error(problem)


def sign_in(store: TokenStore, different_account: bool = False) -> None:
    notice = st.empty()
    minutes = chatgpt_auth.SIGN_IN_TIMEOUT_SECONDS // 60

    def show_fallback_link(url: str) -> None:
        with notice.container():
            st.info(
                "A browser tab should have opened on ChatGPT's sign-in page. Finish there, "
                f"then come back. This page waits up to {minutes} minutes."
            )
            st.link_button("Open the sign-in page", url)

    try:
        with chatgpt_auth.open_http() as http:
            chatgpt_auth.sign_in_with_browser(
                store, http, different_account=different_account, on_ready=show_fallback_link
            )
    except AIError as problem:
        st.session_state["sign_in_error"] = problem
    st.session_state.pop("chatgpt_models", None)  # the list belongs to the old account
    st.rerun()


@st.dialog("You're using your ChatGPT plan")  # OpenAI guideline
def welcome() -> None:
    st.write(
        "Eligible usage in this app uses your ChatGPT plan. "
        "Manage usage in your ChatGPT settings."
    )
    if st.button("Got it"):
        st.rerun()


def model_picker(provider: str, current: str, load_models, only_tools: bool = False) -> None:
    """Show the model in use, and let the user load the live list and save a choice."""
    st.write(f"**Model:** {current or 'not chosen yet'}")
    key = f"{provider}_models"
    if st.button("Load the current model list", key=f"load_{provider}"):
        try:
            st.session_state[key] = load_models()
        except AIError as problem:
            st.session_state[f"{key}_error"] = problem
    show_saved_error(f"{key}_error")
    models = st.session_state.get(key)
    if not models:
        return
    if only_tools:
        models = [model for model in models if model["tools"]]
    if not models:
        st.write("No models were found.")
        return
    names = {
        model["id"]: "  ·  ".join(filter(None, [model["name"], model["id"], model.get("price")]))
        for model in models
    }
    index = list(names).index(current) if current in names else 0
    chosen = st.selectbox(
        "Choose a model", list(names), index=index, format_func=names.get, key=f"pick_{provider}"
    )
    if st.button("Save this model to .env", key=f"save_{provider}"):
        try:
            save_model(provider, chosen)
        except ConfigError as problem:
            st.error(str(problem))
        else:
            st.rerun()


def chatgpt_section(settings: Settings, store: TokenStore) -> None:
    st.subheader("ChatGPT plan")
    try:
        account = chatgpt_auth.active_account(chatgpt_auth.load_state(store))
    except AIError as problem:
        show_error(problem)
        if st.button("Reset saved sign-in"):
            store.clear()
            st.rerun()
        return
    show_saved_error("sign_in_error")
    notice = st.session_state.pop("sign_out_notice", None)
    if notice:
        st.warning(notice)

    if not chatgpt_auth.is_signed_in(account):
        st.write("**Use your ChatGPT plan in this app**")  # OpenAI guideline
        st.caption(
            "A browser tab opens on OpenAI's website. You sign in there, so this app never "
            "sees your password, and approve Fantasy King using your plan."
        )
        if st.button(SIGN_IN_LABEL, type="primary"):
            sign_in(store)
        if account:
            st.caption(f"Last signed in as {account.get('label')}.")
            if st.button("Sign in with a different account"):
                sign_in(store, different_account=True)
        return

    st.success(f"Signed in as {account.get('label')}")
    if account.get("plan_usage_enabled"):
        if not account.get("welcome_seen"):
            chatgpt_auth.mark_welcome_seen(store)
            welcome()
        st.caption("Using ChatGPT plan")  # OpenAI guideline
        st.link_button(MANAGE_USAGE_LABEL, MANAGE_USAGE_URL)
        model_picker("chatgpt", settings.chatgpt_model, lambda: chatgpt.list_models(store))
    else:
        st.warning(
            "You're signed in, but ChatGPT plan usage wasn't approved for this app, "
            "so it can't make AI requests yet."
        )
        if st.button(SIGN_IN_LABEL, type="primary"):
            sign_in(store)

    with st.expander("Account options"):
        if st.button("Sign out"):
            with chatgpt_auth.open_http() as http:
                revoked = chatgpt_auth.sign_out(store, http)
            if not revoked:
                st.session_state["sign_out_notice"] = (
                    "You're signed out on this computer, but OpenAI couldn't be reached to "
                    "cancel the connection. To be sure, also disconnect Fantasy King in "
                    "your ChatGPT settings."
                )
            st.session_state.pop("chatgpt_models", None)
            st.rerun()
        if st.button("Sign in with a different account"):
            sign_in(store, different_account=True)


def openrouter_section(settings: Settings) -> None:
    st.subheader("OpenRouter (backup)")
    st.caption("Uses your OpenRouter API key. Every request costs OpenRouter credits.")
    if settings.openrouter_api_key:
        st.write("**API key:** set")
    else:
        st.write(
            "**API key:** not set. Create one at openrouter.ai/keys, then paste it after "
            "`OPENROUTER_API_KEY=` in your .env file and refresh this page."
        )
    only_tools = st.checkbox("Only show models that can use web search", value=True)
    model_picker("openrouter", settings.openrouter_model, openrouter.list_models, only_tools)


def show_result(name: str, result) -> None:
    st.success("It worked.")
    st.write(result.text)
    for note in result.notes:
        st.warning(note)
    if name == "search":
        if result.web_search_used:
            st.caption(f"Web search was used ({result.web_searches or 'at least 1'} searches).")
        elif not result.notes:
            st.warning("The AI answered without searching the web, so treat this as untested.")
        for source in result.sources:
            st.caption(f"Source: [{source['title']}]({source['url']})")
    st.caption(f"Answered by {PROVIDER_LABELS[result.provider]}, model {result.model}.")


def test_section(settings: Settings) -> None:
    st.subheader("Test the connection")
    provider = st.radio(
        "Provider to test",
        AI_PROVIDERS,
        index=AI_PROVIDERS.index(settings.ai_provider),
        format_func=PROVIDER_LABELS.get,
        horizontal=True,
    )
    st.caption(
        "Each button sends one real request, so it uses a little of your ChatGPT plan "
        "or OpenRouter credits."
    )
    results = st.session_state.setdefault("test_results", {})
    for column, (name, (label, run)) in zip(st.columns(len(TESTS)), TESTS.items()):
        if column.button(label, key=f"test_{name}"):
            with st.spinner("Asking the AI..."):
                try:
                    results[name] = run(settings=replace(settings, ai_provider=provider))
                except AIError as problem:
                    results[name] = problem
    for name, (label, _) in TESTS.items():
        if name in results:
            st.markdown(f"**{label}**")
            if isinstance(results[name], AIError):
                show_error(results[name])
            else:
                show_result(name, results[name])


def main() -> None:
    st.set_page_config(page_title="AI connection · Fantasy King", page_icon="🏈", layout="wide")
    st.title("AI connection")
    try:
        settings = load_settings()
    except ConfigError as problem:
        st.error(str(problem))
        return

    st.info(
        f"**In use now:** {PROVIDER_LABELS[settings.ai_provider]} "
        f"(`AI_PROVIDER={settings.ai_provider}` in your .env file)"
    )
    with st.expander("How to switch providers"):
        st.write(switch_instructions("chatgpt"))
        st.write(switch_instructions("openrouter"))
        st.write(
            "The app never switches by itself. If the provider in use fails, it tells you "
            "what happened and leaves the choice to you."
        )

    left, right = st.columns(2)
    with left:
        chatgpt_section(settings, TokenStore())
    with right:
        openrouter_section(settings)
    st.divider()
    test_section(settings)


main()
