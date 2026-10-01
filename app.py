"""The Fantasy King dashboard.

Start it with start.bat, or from the project folder:
    .venv\\Scripts\\python -m streamlit run app.py
"""

import pandas as pd
import streamlit as st

from fantasy_king.config import ConfigError, load_settings
from fantasy_king.league.base import LeagueDataError, get_league_data
from fantasy_king.models import LeagueSnapshot, Player, RosterSpot

# Required by Yahoo's API terms. Do not remove.
YAHOO_ATTRIBUTION = "Fantasy data provided by Yahoo Fantasy"

SOURCE_LABELS = {
    "sample": "Sample league (fake data)",
    "manual": "Pasted from Yahoo",
    "yahoo_api": "Yahoo Fantasy API",
}
AI_LABELS = {"chatgpt": "ChatGPT plan", "openrouter": "OpenRouter"}
SCORING_LABELS = {"standard": "Standard", "half_ppr": "Half PPR", "ppr": "PPR", "custom": "Custom"}
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]

PLAYER_COLUMNS = {
    "Bye": st.column_config.NumberColumn(format="%d"),
    "Proj": st.column_config.NumberColumn(format="%.1f"),
    "Rostered": st.column_config.NumberColumn(format="%d%%"),
}


def player_row(player: Player, week: int) -> dict:
    status = "BYE" if player.bye_week == week else (player.injury_status or "")
    return {
        "Player": player.name,
        "Pos": player.position,
        "Team": player.nfl_team,
        "Bye": player.bye_week,
        "Status": status,
        "Proj": player.projected_points,
    }


def show_table(rows: list[dict]) -> None:
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config=PLAYER_COLUMNS)


def show_roster(spots: list[RosterSpot], week: int) -> None:
    show_table([{"Slot": spot.slot, **player_row(spot.player, week)} for spot in spots])


def show_my_team(league: LeagueSnapshot) -> None:
    team = league.my_team
    st.subheader(team.name)
    st.markdown("**Starters**")
    show_roster(team.starters, league.week)
    st.markdown("**Bench**")
    show_roster(team.bench, league.week)


def show_matchup(league: LeagueSnapshot) -> None:
    matchup = league.my_matchup
    if matchup is None:
        st.write(f"No matchup found for week {league.week}.")
        return
    mine = league.my_team
    opponent = league.opponent_of(mine.team_id, matchup)
    for column, team in zip(st.columns(2), (mine, opponent)):
        with column:
            st.subheader(team.name)
            st.caption(f"{team.record} · projected {team.projected_total:.1f}")
            show_roster(team.starters, league.week)


def show_league(league: LeagueSnapshot) -> None:
    st.subheader("Standings")
    ranked = sorted(league.teams, key=lambda t: (t.wins, t.points_for), reverse=True)
    standings = [
        {
            "Team": team.name + (" (you)" if team.is_mine else ""),
            "Manager": team.manager,
            "Record": team.record,
            "Points for": team.points_for,
            "Proj this week": team.projected_total,
        }
        for team in ranked
    ]
    st.dataframe(pd.DataFrame(standings), hide_index=True, width="stretch")
    st.subheader("Rosters")
    names = {team.team_id: team.name for team in league.teams}
    chosen = st.selectbox("Team", list(names), format_func=names.get)
    show_roster(league.team(chosen).roster, league.week)


def show_free_agents(league: LeagueSnapshot) -> None:
    position = st.selectbox("Position", ["All", *POSITIONS])
    players = [p for p in league.free_agents if position in ("All", p.position)]
    players.sort(key=lambda p: p.projected_points or 0, reverse=True)
    show_table([{**player_row(p, league.week), "Rostered": p.percent_rostered} for p in players])


def main() -> None:
    st.set_page_config(page_title="Fantasy King", page_icon="🏈", layout="wide")
    st.title("Fantasy King")

    try:
        settings = load_settings()
        league = get_league_data(settings)
    except (ConfigError, LeagueDataError) as problem:
        st.error(str(problem))
        st.caption(YAHOO_ATTRIBUTION)
        return

    rules = league.settings
    st.caption(
        f"{rules.league_name} · {rules.season} · {rules.num_teams} teams · "
        f"{SCORING_LABELS[rules.scoring_type]} · Week {league.week}"
    )
    if league.source == "sample":
        st.info(
            "This is a made-up sample league so you can see the app working. "
            "Every team and player here is invented. Your real league arrives in Phase 3."
        )

    with st.sidebar:
        st.header("Settings in use")
        st.write(f"**League data:** {SOURCE_LABELS[league.source]}")
        st.write(f"**AI provider:** {AI_LABELS[settings.ai_provider]} (not connected yet)")
        st.write(f"**Data from:** {league.captured_at:%a %b %d, %I:%M %p}")
        st.caption("Change these in your .env file, then refresh this page.")

    mine = league.my_team
    matchup = league.my_matchup
    record, projected, opponent, budget = st.columns(4)
    record.metric("Your record", mine.record)
    projected.metric("Your projected points", f"{mine.projected_total:.1f}")
    if matchup:
        other = league.opponent_of(mine.team_id, matchup)
        opponent.metric(f"vs {other.name}", f"{other.projected_total:.1f}")
    if mine.faab_remaining is not None:
        budget.metric("Waiver budget left", f"${mine.faab_remaining}")

    my_team, matchup_tab, league_tab, free_agents = st.tabs(
        ["My team", "Matchup", "League", "Free agents"]
    )
    with my_team:
        show_my_team(league)
    with matchup_tab:
        show_matchup(league)
    with league_tab:
        show_league(league)
    with free_agents:
        show_free_agents(league)

    st.divider()
    st.caption(YAHOO_ATTRIBUTION)


main()
