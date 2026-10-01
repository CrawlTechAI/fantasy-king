"""The one shared data format for league data.

Every data source (sample, manual paste, Yahoo API) must produce a
LeagueSnapshot. The rest of the app only ever works with these classes,
so it never needs to know where the data came from.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

# Roster slots that do not count toward the weekly score.
BENCH_SLOTS = {"BN", "IR"}

ScoringType = Literal["standard", "half_ppr", "ppr", "custom"]
DataSource = Literal["sample", "manual", "yahoo_api"]


class Player(BaseModel):
    name: str
    position: str  # QB, RB, WR, TE, K, or DEF
    nfl_team: str | None = None  # e.g. "KC"; None for a player without a team
    bye_week: int | None = None
    injury_status: str | None = None  # Q, D, O, IR, ... or None when healthy
    projected_points: float | None = None
    percent_rostered: float | None = None
    sleeper_id: str | None = None  # filled in once matched to Sleeper's player list
    yahoo_id: str | None = None


class RosterSpot(BaseModel):
    slot: str  # QB, RB, WR, TE, W/R/T, K, DEF, BN, or IR
    player: Player

    @property
    def is_starter(self) -> bool:
        return self.slot not in BENCH_SLOTS


class Team(BaseModel):
    team_id: str
    name: str
    manager: str | None = None
    is_mine: bool = False
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: float = 0.0
    faab_remaining: int | None = None
    roster: list[RosterSpot] = Field(default_factory=list)

    @property
    def starters(self) -> list[RosterSpot]:
        return [spot for spot in self.roster if spot.is_starter]

    @property
    def bench(self) -> list[RosterSpot]:
        return [spot for spot in self.roster if not spot.is_starter]

    @property
    def projected_total(self) -> float:
        return round(sum(spot.player.projected_points or 0 for spot in self.starters), 2)

    @property
    def record(self) -> str:
        return f"{self.wins}-{self.losses}" + (f"-{self.ties}" if self.ties else "")


class Matchup(BaseModel):
    week: int
    team_a_id: str
    team_b_id: str
    team_a_points: float | None = None  # actual score; None until games are played
    team_b_points: float | None = None


class LeagueSettings(BaseModel):
    league_name: str
    season: int
    num_teams: int
    scoring_type: ScoringType
    roster_slots: dict[str, int]  # e.g. {"QB": 1, "RB": 2, "BN": 6}
    waiver_type: str | None = None  # e.g. "FAAB" or "rolling"
    faab_budget: int | None = None
    trade_deadline: date | None = None
    playoff_start_week: int | None = None
    scoring_notes: str | None = None  # anything unusual about this league's scoring


class LeagueSnapshot(BaseModel):
    """Everything known about the league at one moment in time."""

    source: DataSource
    captured_at: datetime
    week: int
    settings: LeagueSettings
    teams: list[Team]
    matchups: list[Matchup] = Field(default_factory=list)
    free_agents: list[Player] = Field(default_factory=list)

    def team(self, team_id: str) -> Team:
        for team in self.teams:
            if team.team_id == team_id:
                return team
        raise KeyError(f"No team with id {team_id!r} in this league")

    @property
    def my_team(self) -> Team:
        for team in self.teams:
            if team.is_mine:
                return team
        raise ValueError("No team in this league is marked as yours")

    @property
    def my_matchup(self) -> Matchup | None:
        mine = self.my_team.team_id
        for matchup in self.matchups:
            if matchup.week == self.week and mine in (matchup.team_a_id, matchup.team_b_id):
                return matchup
        return None

    def opponent_of(self, team_id: str, matchup: Matchup) -> Team:
        other = matchup.team_b_id if matchup.team_a_id == team_id else matchup.team_a_id
        return self.team(other)
