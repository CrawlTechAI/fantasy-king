# Fantasy King

A personal assistant for one Yahoo Fantasy Football league. It looks at your league and suggests:

1. Who to start and sit this week, with a short reason for each
2. Who to add and drop from the waiver wire, ranked by priority
3. Trades that help you and that the other manager could plausibly accept
4. Alerts for news on your players (injuries, inactives, bye weeks, role changes)

The app only makes suggestions. You make every move yourself in the Yahoo app. It never logs in to Yahoo or changes your team.

## Status

This project is being built in phases.

| Phase | What it adds | Status |
|---|---|---|
| 1 | Project setup and a dashboard showing a made-up sample league | Done |
| 2 | AI connection (ChatGPT plan, with OpenRouter as backup) | Built. Confirm it on your own account with the steps under "Connect the AI". |
| 3 | Pasting in your real league data, plus Sleeper player data | Not started |
| 4 | Lineup, waiver, and trade suggestions | Not started |
| 5 | Full dashboard and daily email summary | Not started |
| 6 | Scheduled checks, error messages, and low usage | Not started |
| 7 | Yahoo Fantasy API mode | Waiting on Yahoo approval |

## First-time setup

You need [Python](https://www.python.org/downloads/) 3.10 or newer. These steps are for Windows.

1. Open the project folder in File Explorer, click the address bar, type `powershell`, and press Enter. A terminal opens in the project folder.
2. Create the virtual environment. This is a private copy of Python for this project, so its packages do not mix with anything else on your computer:

   ```
   python -m venv .venv
   ```

3. Install the packages the app needs:

   ```
   .venv\Scripts\python -m pip install -r requirements.txt
   ```

4. Create your settings file by copying the example:

   ```
   copy .env.example .env
   ```

## Start and stop

**Start:** double-click `start.bat`. A black window opens and, a few seconds later, your browser opens the dashboard at http://localhost:8501.

The first time, the black window may ask for an email address. That is Streamlit (the dashboard tool) offering a newsletter. Leave it blank and press Enter.

**Stop:** click the black window and press `Ctrl+C`, or close the window.

## Connect the AI

The app can use one of two AI services. You choose with `AI_PROVIDER` in `.env`.

| | ChatGPT plan (`chatgpt`) | OpenRouter (`openrouter`) |
|---|---|---|
| What you need | A ChatGPT subscription | An OpenRouter account with credits |
| What it costs | Counts against your ChatGPT plan's usage | Charged per request to your OpenRouter credits |
| How you connect | Sign in through your browser. No API key. | Paste an API key into `.env` |

Everything below happens on the **AI connection** page. Start the dashboard, then click **AI connection** in the left sidebar.

### Option A: your ChatGPT plan

This uses OpenAI's "Sign in with ChatGPT" for open-source apps. OpenAI offers it only to open-source, locally run apps, which is why this repository is public. The feature is a preview, and OpenAI's docs do not say which ChatGPT plans qualify, so step 6 is how you find out whether yours does.

1. Make sure `.env` has the line `AI_PROVIDER=chatgpt`.
2. On the AI connection page, click **Continue with ChatGPT**. A browser tab opens on OpenAI's website (`auth.openai.com`).
3. Sign in to ChatGPT there. You type your password on OpenAI's page, so this app never sees it.
4. OpenAI shows an approval screen naming the app **Fantasy King**. Approve it, including the permission to use your ChatGPT plan. The first time, this step also registers the app with your account; there is no separate sign-up form.
5. The tab says "You can close this tab". Go back to the dashboard. It now says **Signed in as** your email and **Using ChatGPT plan**.
6. Click **Load the current model list**, pick a model, and click **Save this model to .env**. The list comes from your own account, so it only shows models you may use.
7. Under **Test the connection**, click each of the three buttons. See "What the tests mean" below.

You stay signed in. The app renews the sign-in by itself in the background. If you don't use the app for 30 days, you will need to click **Continue with ChatGPT** again.

To see or change how much of your plan this app may use, click **Manage usage** (it opens your ChatGPT settings).

### Option B: OpenRouter

1. Create an account at [openrouter.ai](https://openrouter.ai) and add credits.
2. Create an API key at [openrouter.ai/keys](https://openrouter.ai/keys).
3. Open `.env` in Notepad. Paste the key right after the equals sign on the `OPENROUTER_API_KEY` line, with no spaces or quotes. Save.
4. On the AI connection page, under **OpenRouter (backup)**, click **Load the current model list**. Each model shows its current price. Pick one and click **Save this model to .env**.
5. Under **Test the connection**, choose **OpenRouter** and click each of the three buttons.

Web search on OpenRouter costs extra per search, on top of the model's price. `MAX_WEB_SEARCHES_PER_RUN` in `.env` limits how many searches one request may run, with one caveat:

- For the search engines OpenRouter runs itself, the limit is firm.
- Some models use their provider's own built-in search instead. OpenRouter's docs say the per-tool limit is then passed on only to Anthropic models and ignored by other providers. The app also sends OpenRouter's overall tool budget, which is the limit that still applies, but the docs do not say exactly how a provider's own searches count against it. Treat the limit as a best effort for those models.

After a web search test, the page shows how many searches were actually run, so you can check.

### What the tests mean

| Button | What it checks | Needed later for |
|---|---|---|
| Test a simple question | The AI answers at all | Everything |
| Test web search | The AI can search the web | Player news |
| Test reading an image | The AI can read a picture | League screenshots |

Each button sends one real request, so it uses a little of your plan or credits.

If the web search test says the answer did not use web search, your model or account can't search. That is not a failure: the app carries on without web search and will rely on Sleeper for player news.

### Switching providers

1. Open `.env` in Notepad.
2. Change the `AI_PROVIDER` line to `AI_PROVIDER=openrouter` or `AI_PROVIDER=chatgpt`.
3. Save, then refresh the dashboard.

The app never switches by itself. If the provider in use fails, it tells you what happened and how to switch, and waits for you. This is deliberate: OpenRouter costs money, so it is only used when you choose it.

### Where your sign-in is kept

Your ChatGPT sign-in is saved in `%LOCALAPPDATA%\FantasyKing\`, outside this project folder, so it can never be uploaded to GitHub. On Windows the file is encrypted so that only your Windows account on this computer can read it. To remove it, click **Sign out** under **Account options**.

### If something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| "You aren't signed in with ChatGPT yet" | No sign-in is saved | Click **Continue with ChatGPT** |
| "Your ChatGPT sign-in has expired or was disconnected" | 30 days passed, or the app was disconnected in ChatGPT settings | Click **Continue with ChatGPT** |
| "You declined the request on ChatGPT's page" | The approval screen was cancelled | Sign in again and approve it |
| "plan usage wasn't approved" | You signed in but did not allow plan usage | Click **Continue with ChatGPT** and approve plan usage |
| "Sign-in wasn't finished within 5 minutes" | The browser tab was closed or left waiting | Click **Continue with ChatGPT** again |
| "Usage limit reached" | Your plan's limit, or this app's limit, is used up | Click **Manage usage**, wait for the reset, or switch to OpenRouter |
| "ChatGPT plan usage isn't available for this ChatGPT account, workspace, or region" | Your account can't use this feature | Signing in again won't help. Switch to OpenRouter. |
| "ChatGPT plan usage is unavailable right now, or isn't switched on for your account" | A temporary outage, or the preview isn't enabled for you | Try again later. If it never works, switch to OpenRouter. |
| "OpenRouter didn't accept your API key" | The key is wrong or was deleted | Check `OPENROUTER_API_KEY` in `.env` |
| "Your OpenRouter account is out of credits" | No credits left | Add credits at openrouter.ai |
| "Couldn't reach ChatGPT" or "Couldn't reach OpenRouter" | No internet connection | Check your connection and try again |

You can also check the connection from a terminal. These commands send no question to an AI, so they cost nothing:

```
.venv\Scripts\python -m fantasy_king.ai status
.venv\Scripts\python -m fantasy_king.ai models openrouter mini
```

The second one lists OpenRouter models whose name contains "mini", with prices.

## Settings

Settings live in the `.env` file. Open it with Notepad, change a value, save, and refresh the dashboard.

| Setting | Choices | Meaning |
|---|---|---|
| `LEAGUE_DATA_SOURCE` | `sample`, `manual`, `yahoo_api` | Where league data comes from. Only `sample` works so far. |
| `AI_PROVIDER` | `chatgpt`, `openrouter` | Which AI service to use. |
| `CHATGPT_MODEL` | A model name | The model used with your ChatGPT plan. Saved for you by the AI connection page. |
| `OPENROUTER_MODEL` | A model ID | The model used with OpenRouter. Saved for you by the AI connection page. Do not add `:online`. |
| `OPENROUTER_API_KEY` | Your key | Only needed for OpenRouter. |
| `WEB_SEARCH_ENABLED` | `true`, `false` | Whether the AI may search the web. |
| `MAX_WEB_SEARCHES_PER_RUN` | A whole number, 0 to 30 | A limit on searches per request. `0` means never search. On OpenRouter it is firm for OpenRouter's own search engines and a best effort for a provider's built-in search. On the ChatGPT plan no limit can be sent, so only `0` has an effect. |

`.env.example` lists every setting, including ones used by later phases.

## What is in this folder

| Item | What it is |
|---|---|
| `app.py` | The dashboard's home page |
| `pages/` | The dashboard's other pages (so far, AI connection) |
| `start.bat` | Double-click to start the dashboard |
| `fantasy_king/` | The app's code |
| `fantasy_king/models.py` | The one shared format for league data |
| `fantasy_king/league/` | Where league data comes from (sample, pasted, or Yahoo API) |
| `fantasy_king/ai/client.py` | `ask_ai()`, the one function the app uses to talk to either AI service |
| `fantasy_king/ai/chatgpt_auth.py` | Sign in with ChatGPT |
| `fantasy_king/ai/chatgpt.py`, `openrouter.py` | The two AI services |
| `fantasy_king/ai/errors.py` | Turns AI failures into plain-language messages |
| `sample_data/` | A made-up league. Every name in it is invented. |
| `scripts/check_before_push.py` | Safety check that runs before anything is uploaded |
| `tests/` | Automated tests |
| `.env.example` | Blank template for your settings |
| `.env` | Your real settings. Stays on your computer. |
| `data/` | Your league data and database. Stays on your computer. |

## Keeping private things private

This repository is public, so nothing personal can be uploaded.

- API keys and the email password go only in `.env`. The ChatGPT sign-in is kept outside this folder entirely (see "Where your sign-in is kept").
- `.gitignore` tells Git to skip `.env`, the `data/` folder, databases, images, and any saved sign-in file.
- The app never prints or logs a key or sign-in token.
- Before every upload, run the safety check:

  ```
  .venv\Scripts\python scripts\check_before_push.py
  ```

  It lists every file that would be uploaded and says `FAILED` if any of them is private or contains something that looks like a key or token.

## Run the tests

```
.venv\Scripts\python -m pytest
```

The tests use a pretend OpenAI and OpenRouter. They never sign in, never contact a real AI service, and cost nothing.

## Data sources and credits

- Fantasy data provided by Yahoo Fantasy.
- NFL player information and trending adds and drops come from the [Sleeper API](https://docs.sleeper.com/).

## License

[MIT](LICENSE). In plain language: anyone may use, copy, change, and share this code, including in their own projects, as long as they keep the copyright notice and license text with it. The code comes with no warranty, so if it breaks or gives bad advice, the author is not liable.
