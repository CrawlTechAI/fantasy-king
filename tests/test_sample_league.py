from collections import Counter

import pytest

from fantasy_king.config import Settings
from fantasy_king.league.base import LeagueDataError, get_league_data
from fantasy_king.league.sample import load_sample_league


def test_sample_league_loads_through_the_shared_entry_point():
    league = get_league_data(Settings(league_data_source="sample", ai_provider="chatgpt"))
    assert league.source == "sample"
    assert len(league.teams) == league.settings.num_teams


def test_every_roster_matches_the_league_roster_slots():
    league = load_sample_league()
    expected = {slot: n for slot, n in league.settings.roster_slots.items() if slot != "IR"}
    for team in league.teams:
        assert Counter(spot.slot for spot in team.roster) == expected, team.name


def test_exactly_one_team_is_mine_and_it_has_a_matchup():
    league = load_sample_league()
    assert sum(team.is_mine for team in league.teams) == 1
    matchup = league.my_matchup
    assert matchup is not None
    assert league.opponent_of(league.my_team.team_id, matchup) is not league.my_team


def test_projected_total_counts_starters_only():
    team = load_sample_league().my_team
    starters = sum(spot.player.projected_points for spot in team.starters)
    assert team.projected_total == round(starters, 2)
    assert len(team.bench) == 6


def test_no_player_appears_twice():
    league = load_sample_league()
    names = [spot.player.name for team in league.teams for spot in team.roster]
    names += [player.name for player in league.free_agents]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("source", ["manual", "yahoo_api"])
def test_unbuilt_sources_explain_themselves(source):
    with pytest.raises(LeagueDataError, match="not built yet"):
        get_league_data(Settings(league_data_source=source, ai_provider="chatgpt"))
