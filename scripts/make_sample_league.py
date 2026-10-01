"""Builds the fake league saved in sample_data/sample_league.json.

Run from the project folder:
    .venv\\Scripts\\python scripts\\make_sample_league.py

Every player, team, and manager name is invented. The same file is produced
every time, so re-running it changes nothing unless this script is edited.
"""

import random
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy_king.league.sample import SAMPLE_LEAGUE_FILE  # noqa: E402
from fantasy_king.models import (  # noqa: E402
    LeagueSettings,
    LeagueSnapshot,
    Matchup,
    Player,
    RosterSpot,
    Team,
)

WEEK = 4
MY_TEAM_ID = "1"

ROSTER_SLOTS = {"QB": 1, "WR": 2, "RB": 2, "TE": 1, "W/R/T": 1, "K": 1, "DEF": 1, "BN": 6, "IR": 1}
STARTING_ORDER = [
    ("QB", {"QB"}),
    ("WR", {"WR"}),
    ("WR", {"WR"}),
    ("RB", {"RB"}),
    ("RB", {"RB"}),
    ("TE", {"TE"}),
    ("W/R/T", {"WR", "RB", "TE"}),
    ("K", {"K"}),
    ("DEF", {"DEF"}),
]
PLAYERS_PER_TEAM = {"QB": 2, "RB": 5, "WR": 5, "TE": 1, "K": 1, "DEF": 1}
FREE_AGENTS = {"QB": 4, "RB": 8, "WR": 8, "TE": 4, "K": 3, "DEF": 3}
PROJECTION_RANGE = {
    "QB": (14.0, 24.0),
    "RB": (6.0, 20.0),
    "WR": (6.0, 19.0),
    "TE": (5.0, 14.0),
    "K": (6.0, 10.0),
    "DEF": (5.0, 10.0),
}

NFL_TEAMS = (
    "ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC "
    "LV LAC LAR MIA MIN NE NO NYG NYJ PHI PIT SF SEA TB TEN WAS"
).split()

FIRST_NAMES = (
    "Abel Barrett Caspian Dashiell Ellis Fenwick Gideon Harlan Ignatius Jasper "
    "Kellan Leopold Maddox Nolan Osgood Percival Quentin Rafferty Silas Thaddeus "
    "Ulric Vaughn Wendell Xavier Yates Zebulon Alaric Benedict Cormac Dexter"
).split()
LAST_NAMES = (
    "Thunderbrook Quickwater Ironwood Fairweather Stonebridge Goldsworth Hawkridge "
    "Underhill Winterbourne Ashgrove Marshbank Copperfield Oakenshaw Pennywhistle "
    "Ravenscroft Tumbleweed Yarrowby Zephyrson Applegate Birchfield Cinderford "
    "Elderwood Foxglove Greystone Hollowell Inkwell Kettleburn Larkspur Mossgrove "
    "Northcliff Orchardson Puddlefoot Quarryman Rookwood Saddleworth Thistledown"
).split()

FANTASY_TEAMS = [
    ("Your Sample Team", "You"),
    ("Gridiron Gophers", "Morgan"),
    ("End Zone Otters", "Riley"),
    ("Blitz Badgers", "Casey"),
    ("Hail Mary Herons", "Jordan"),
    ("Red Zone Raccoons", "Avery"),
    ("Fumble Foxes", "Quinn"),
    ("Punt Pandas", "Rowan"),
    ("Sack Salamanders", "Emerson"),
    ("Audible Armadillos", "Sawyer"),
]


class LeagueBuilder:
    def __init__(self, seed: int = 2026):
        self.rng = random.Random(seed)
        self.bye_weeks = {team: self.rng.randint(5, 14) for team in NFL_TEAMS}
        self.names = [f"{first} {last}" for first in FIRST_NAMES for last in LAST_NAMES]
        self.rng.shuffle(self.names)
        self.defenses = list(NFL_TEAMS)
        self.rng.shuffle(self.defenses)

    def player(self, position: str, rostered: bool) -> Player:
        low, high = PROJECTION_RANGE[position]
        if not rostered:
            low, high = low * 0.5, high * 0.65
        nfl_team = self.defenses.pop() if position == "DEF" else self.rng.choice(NFL_TEAMS)
        name = f"{nfl_team} Defense" if position == "DEF" else self.names.pop()
        injury = None
        if position not in ("K", "DEF") and self.rng.random() < 0.1:
            injury = self.rng.choice(["Q", "Q", "D"])
        return Player(
            name=name,
            position=position,
            nfl_team=nfl_team,
            bye_week=self.bye_weeks[nfl_team],
            injury_status=injury,
            projected_points=round(self.rng.uniform(low, high), 1),
            percent_rostered=self.rng.randint(70, 100) if rostered else self.rng.randint(2, 60),
        )

    def roster(self) -> list[RosterSpot]:
        players = [
            self.player(position, rostered=True)
            for position, count in PLAYERS_PER_TEAM.items()
            for _ in range(count)
        ]
        remaining = sorted(players, key=lambda p: p.projected_points, reverse=True)
        spots = []
        for slot, positions in STARTING_ORDER:
            best = next(p for p in remaining if p.position in positions)
            remaining.remove(best)
            spots.append(RosterSpot(slot=slot, player=best))
        return spots + [RosterSpot(slot="BN", player=p) for p in remaining]

    def team(self, number: int, name: str, manager: str) -> Team:
        wins = self.rng.randint(0, WEEK - 1)
        return Team(
            team_id=str(number),
            name=name,
            manager=manager,
            is_mine=str(number) == MY_TEAM_ID,
            wins=wins,
            losses=WEEK - 1 - wins,
            points_for=round(self.rng.uniform(290, 410), 1),
            faab_remaining=self.rng.randint(60, 100),
            roster=self.roster(),
        )

    def build(self) -> LeagueSnapshot:
        teams = [
            self.team(number, name, manager)
            for number, (name, manager) in enumerate(FANTASY_TEAMS, start=1)
        ]
        add_lineup_problems(teams[0])
        free_agents = [
            self.player(position, rostered=False)
            for position, count in FREE_AGENTS.items()
            for _ in range(count)
        ]
        matchups = [
            Matchup(week=WEEK, team_a_id=teams[i].team_id, team_b_id=teams[i + 1].team_id)
            for i in range(0, len(teams), 2)
        ]
        return LeagueSnapshot(
            source="sample",
            captured_at=datetime(2026, 9, 30, 9, 0),
            week=WEEK,
            settings=LeagueSettings(
                league_name="Sample League (fake data)",
                season=2026,
                num_teams=len(teams),
                scoring_type="half_ppr",
                roster_slots=ROSTER_SLOTS,
                waiver_type="FAAB",
                faab_budget=100,
                trade_deadline=date(2026, 11, 21),
                playoff_start_week=15,
            ),
            teams=teams,
            matchups=matchups,
            free_agents=free_agents,
        )


def add_lineup_problems(team: Team) -> None:
    """Give your sample team a starter who is out and one who is questionable,
    so the lineup advice built in later phases has something to catch."""
    wide_receiver = next(spot.player for spot in team.roster if spot.slot == "WR")
    wide_receiver.injury_status = "O"
    wide_receiver.projected_points = 0.0
    running_back = next(spot.player for spot in team.roster if spot.slot == "RB")
    running_back.injury_status = "Q"


if __name__ == "__main__":
    snapshot = LeagueBuilder().build()
    SAMPLE_LEAGUE_FILE.parent.mkdir(exist_ok=True)
    SAMPLE_LEAGUE_FILE.write_text(
        snapshot.model_dump_json(indent=2, exclude_none=True) + "\n", encoding="utf-8"
    )
    players = sum(len(team.roster) for team in snapshot.teams) + len(snapshot.free_agents)
    print(f"Wrote {SAMPLE_LEAGUE_FILE} ({len(snapshot.teams)} teams, {players} players)")
