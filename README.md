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
| 2 | AI connection (ChatGPT plan, with OpenRouter as backup) | Not started |
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

## Settings

Settings live in the `.env` file. Open it with Notepad, change a value, save, and refresh the dashboard.

| Setting | Choices | Meaning |
|---|---|---|
| `LEAGUE_DATA_SOURCE` | `sample`, `manual`, `yahoo_api` | Where league data comes from. Only `sample` works so far. |
| `AI_PROVIDER` | `chatgpt`, `openrouter` | Which AI service to use (Phase 2). |

`.env.example` lists every setting, including ones used by later phases.

## What is in this folder

| Item | What it is |
|---|---|
| `app.py` | The dashboard |
| `start.bat` | Double-click to start the dashboard |
| `fantasy_king/` | The app's code |
| `fantasy_king/models.py` | The one shared format for league data |
| `fantasy_king/league/` | Where league data comes from (sample, pasted, or Yahoo API) |
| `sample_data/` | A made-up league. Every name in it is invented. |
| `scripts/check_before_push.py` | Safety check that runs before anything is uploaded |
| `tests/` | Automated tests |
| `.env.example` | Blank template for your settings |
| `.env` | Your real settings. Stays on your computer. |
| `data/` | Your league data and database. Stays on your computer. |

## Keeping private things private

This repository is public, so nothing personal can be uploaded.

- Secrets (sign-in tokens, API keys, email password) go only in `.env` or in a token file outside this folder.
- `.gitignore` tells Git to skip `.env`, the `data/` folder, databases, and images.
- Before every upload, run the safety check:

  ```
  .venv\Scripts\python scripts\check_before_push.py
  ```

  It lists every file that would be uploaded and says `FAILED` if any of them is private or contains something that looks like a key or token.

## Run the tests

```
.venv\Scripts\python -m pytest
```

## Data sources and credits

- Fantasy data provided by Yahoo Fantasy.
- NFL player information and trending adds and drops come from the [Sleeper API](https://docs.sleeper.com/).

## License

[MIT](LICENSE). In plain language: anyone may use, copy, change, and share this code, including in their own projects, as long as they keep the copyright notice and license text with it. The code comes with no warranty, so if it breaks or gives bad advice, the author is not liable.
