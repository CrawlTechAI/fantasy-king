"""The built-in fake league, used to try the app before real data exists."""

from fantasy_king.config import SAMPLE_DATA_DIR
from fantasy_king.models import LeagueSnapshot

SAMPLE_LEAGUE_FILE = SAMPLE_DATA_DIR / "sample_league.json"


def load_sample_league() -> LeagueSnapshot:
    return LeagueSnapshot.model_validate_json(SAMPLE_LEAGUE_FILE.read_text(encoding="utf-8"))
