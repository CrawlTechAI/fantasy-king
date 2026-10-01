"""The single entry point for league data.

The rest of the app calls get_league_data() and gets back a LeagueSnapshot.
Which source it came from is decided by LEAGUE_DATA_SOURCE in .env.
"""

from fantasy_king.config import Settings, load_settings
from fantasy_king.models import LeagueSnapshot


class LeagueDataError(Exception):
    """League data could not be loaded. The message is written for the user."""


def get_league_data(settings: Settings | None = None) -> LeagueSnapshot:
    settings = settings or load_settings()
    source = settings.league_data_source

    if source == "sample":
        from fantasy_king.league.sample import load_sample_league

        return load_sample_league()

    if source == "manual":
        raise LeagueDataError(
            "Manual mode is not built yet (it arrives in Phase 3). "
            "For now, set LEAGUE_DATA_SOURCE=sample in your .env file."
        )

    raise LeagueDataError(
        "Yahoo API mode is not built yet (it arrives in Phase 7, after Yahoo approves "
        "your application). For now, set LEAGUE_DATA_SOURCE=sample in your .env file."
    )
