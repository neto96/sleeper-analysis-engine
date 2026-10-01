import requests
import json
from pathlib import Path
from datetime import datetime, timezone


# ============================================================
# SLEEPER FANTASY SNAPSHOT V3
# ============================================================
#
# League: Nuevo León Football League
#
# V3 goals:
#   - Full league snapshot
#   - Rosters
#   - Standings
#   - Waiver priority
#   - Available players
#   - Recent transactions
#   - Proper trade reconstruction
#   - Matchups
#   - JSON + Markdown output
#
# Data source:
#   Sleeper public API
#
# ============================================================


LEAGUE_ID = "1389736505374691328"
MY_ROSTER_ID = 3

BASE_URL = "https://api.sleeper.app/v1"

OUTPUT_DIR = Path(__file__).parent / "snapshots"


# ============================================================
# API HELPER
# ============================================================

def get_json(endpoint):
    url = f"{BASE_URL}{endpoint}"

    response = requests.get(
        url,
        timeout=30,
        headers={
            "Accept": "application/json"
        }
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# GENERAL HELPERS
# ============================================================

def clean_name(value):
    if value is None:
        return ""

    return " ".join(str(value).split()).strip()


def player_name(player_id, players):
    player = players.get(str(player_id))

    if not player:
        return str(player_id)

    name = (
        player.get("full_name")
        or " ".join(
            x for x in [
                player.get("first_name"),
                player.get("last_name")
            ]
            if x
        )
        or str(player_id)
    )

    return clean_name(name)


def player_info(player_id, players):
    player_id = str(player_id)

    player = players.get(player_id)

    if not player:
        return {
            "player_id": player_id,
            "name": player_id,
            "position": None,
            "fantasy_positions": [],
            "team": None,
            "status": None,
            "injury_status": None,
            "search_rank": None
        }

    return {
        "player_id": player_id,
        "name": player_name(player_id, players),
        "position": player.get("position"),
        "fantasy_positions": player.get(
            "fantasy_positions"
        ) or [],
        "team": player.get("team"),
        "status": player.get("status"),
        "injury_status": player.get(
            "injury_status"
        ),
        "search_rank": player.get("search_rank")
    }


def player_label(player_id, players):
    info = player_info(player_id, players)

    name = info["name"]
    position = info["position"] or "?"
    team = info["team"] or "FA"

    result = f"{name} {position}, {team}"

    if info["injury_status"]:
        result += f" ({info['injury_status']})"

    return result


def get_team_name(user, roster):
    user_metadata = (
        user.get("metadata") or {}
        if user
        else {}
    )

    roster_metadata = (
        roster.get("metadata") or {}
        if roster
        else {}
    )

    return clean_name(
        user_metadata.get("team_name")
        or roster_metadata.get("team_name")
        or (
            user.get("display_name")
            if user
            else None
        )
        or (
            user.get("username")
            if user
            else None
        )
        or f"Roster {roster.get('roster_id')}"
    )


def get_record(settings):
    settings = settings or {}

    wins = int(settings.get("wins", 0) or 0)
    losses = int(settings.get("losses", 0) or 0)
    ties = int(settings.get("ties", 0) or 0)

    if ties:
        return f"{wins}-{losses}-{ties}"

    return f"{wins}-{losses}"


def get_points(settings):
    settings = settings or {}

    pf = float(
        settings.get(
            "fpts_decimal",
            settings.get("fpts", 0)
        ) or 0
    )

    pa = float(
        settings.get(
            "fpts_against_decimal",
            settings.get("fpts_against", 0)
        ) or 0
    )

    return {
        "pf": pf,
        "pa": pa
    }


def md(value):
    return (
        str(value or "")
        .replace("|", "\\|")
        .replace("\n", " ")
        .strip()
    )


# ============================================================
# WAIVER / FREE AGENT FILTERS
# ============================================================

def is_useful_fantasy_player(player):
    valid_positions = {
        "QB",
        "RB",
        "WR",
        "TE",
        "K",
        "DEF"
    }

    position = player.get("position")

    if position not in valid_positions:
        return False

    name = clean_name(
        player.get("full_name")
        or " ".join(
            x for x in [
                player.get("first_name"),
                player.get("last_name")
            ]
            if x
        )
    )

    if not name:
        return False

    lowered = name.lower()

    if "player invalid" in lowered:
        return False

    if lowered == "duplicate player":
        return False

    return True


def is_active_enough_for_waivers(player):
    position = player.get("position")

    # Kickers can have no NFL team in Sleeper.
    if position != "K" and not player.get("team"):
        return False

    status = str(
        player.get("status") or ""
    ).lower()

    if status in {
        "inactive",
        "retired"
    }:
        return False

    return True


def position_sort_value(position):
    order = {
        "QB": 1,
        "RB": 2,
        "WR": 3,
        "TE": 4,
        "K": 5,
        "DEF": 6
    }

    return order.get(position, 99)


# ============================================================
# TRANSACTION RECONSTRUCTION
# ============================================================

def reconstruct_trade(tx, roster_data, players):
    """
    Sleeper trade transactions contain:

        adds[player_id] = roster receiving player
        drops[player_id] = roster giving up player

    We use those mappings to reconstruct each side.
    """

    roster_ids = [
        int(x)
        for x in (tx.get("roster_ids") or [])
    ]

    sides = {}

    for roster_id in roster_ids:
        roster = roster_data.get(str(roster_id))

        if roster:
            sides[roster_id] = {
                "roster_id": roster_id,
                "team_name": roster["team_name"],
                "owner": roster["owner"],
                "gave": [],
                "received": []
            }
        else:
            sides[roster_id] = {
                "roster_id": roster_id,
                "team_name": f"Roster {roster_id}",
                "owner": "",
                "gave": [],
                "received": []
            }

    adds = tx.get("adds") or {}
    drops = tx.get("drops") or {}

    # --------------------------------------------------------
    # Players received
    # --------------------------------------------------------

    for player_id, receiving_roster in adds.items():

        receiving_roster = int(receiving_roster)

        if receiving_roster not in sides:
            sides[receiving_roster] = {
                "roster_id": receiving_roster,
                "team_name": (
                    f"Roster {receiving_roster}"
                ),
                "owner": "",
                "gave": [],
                "received": []
            }

        sides[receiving_roster]["received"].append(
            player_info(player_id, players)
        )

    # --------------------------------------------------------
    # Players given up
    # --------------------------------------------------------

    for player_id, giving_roster in drops.items():

        giving_roster = int(giving_roster)

        if giving_roster not in sides:
            sides[giving_roster] = {
                "roster_id": giving_roster,
                "team_name": (
                    f"Roster {giving_roster}"
                ),
                "owner": "",
                "gave": [],
                "received": []
            }

        sides[giving_roster]["gave"].append(
            player_info(player_id, players)
        )

    # Sort players alphabetically for stable output.
    for side in sides.values():

        side["gave"].sort(
            key=lambda p: p["name"].lower()
        )

        side["received"].sort(
            key=lambda p: p["name"].lower()
        )

    # --------------------------------------------------------
    # Create simple summary
    # --------------------------------------------------------

    side_list = list(sides.values())

    summary_parts = []

    if len(side_list) == 2:

        a = side_list[0]
        b = side_list[1]

        a_received = ", ".join(
            p["name"]
            for p in a["received"]
        ) or "nothing"

        b_received = ", ".join(
            p["name"]
            for p in b["received"]
        ) or "nothing"

        summary_parts.append(
            f"{a['team_name']} received "
            f"{a_received}; "
            f"{b['team_name']} received "
            f"{b_received}"
        )

    return {
        "transaction_id": tx.get("transaction_id"),
        "type": "trade",
        "status": tx.get("status"),
        "created": tx.get("created"),
        "creator": tx.get("creator"),
        "roster_ids": roster_ids,
        "sides": side_list,
        "draft_picks": tx.get("draft_picks") or [],
        "waiver_budget": tx.get("waiver_budget") or [],
        "summary": (
            summary_parts[0]
            if summary_parts
            else ""
        ),
        "raw_transaction": tx
    }


# ============================================================
# TRANSACTION FORMATTER
# ============================================================

def build_transaction_record(
    tx,
    week,
    roster_data,
    players
):

    tx_type = tx.get("type")

    base = {
        "week": week,
        "transaction_id": tx.get(
            "transaction_id"
        ),
        "type": tx_type,
        "status": tx.get("status"),
        "created": tx.get("created"),
        "creator": tx.get("creator"),
        "roster_ids": tx.get(
            "roster_ids"
        ) or []
    }

    # --------------------------------------------------------
    # Trade
    # --------------------------------------------------------

    if tx_type == "trade":

        trade = reconstruct_trade(
            tx,
            roster_data,
            players
        )

        base["trade"] = trade

        return base

    # --------------------------------------------------------
    # Waiver / free agent / other
    # --------------------------------------------------------

    base["adds"] = [
        player_info(player_id, players)
        for player_id in (
            tx.get("adds") or {}
        ).keys()
    ]

    base["drops"] = [
        player_info(player_id, players)
        for player_id in (
            tx.get("drops") or {}
        ).keys()
    ]

    base["draft_picks"] = (
        tx.get("draft_picks") or []
    )

    base["waiver_budget"] = (
        tx.get("waiver_budget") or []
    )

    return base


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("==========================================")
    print("SLEEPER FANTASY SNAPSHOT V3")
    print("==========================================")
    print()

    # --------------------------------------------------------
    # Core league data
    # --------------------------------------------------------

    print("Loading league...")

    league = get_json(
        f"/league/{LEAGUE_ID}"
    )

    print("Loading users...")

    users = get_json(
        f"/league/{LEAGUE_ID}/users"
    )

    print("Loading rosters...")

    rosters = get_json(
        f"/league/{LEAGUE_ID}/rosters"
    )

    print("Loading NFL state...")

    nfl_state = get_json(
        "/state/nfl"
    )

    current_week = int(
        nfl_state.get("week", 1)
    )

    season = str(
        league.get("season")
        or nfl_state.get("season")
        or datetime.now().year
    )

    print(
        f"Season: {season}"
    )

    print(
        f"Current NFL week: {current_week}"
    )

    print()

    # --------------------------------------------------------
    # Player database
    # --------------------------------------------------------

    print("Loading NFL player database...")

    players = get_json(
        "/players/nfl"
    )

    print(
        f"Loaded {len(players):,} players."
    )

    print()

    # --------------------------------------------------------
    # User lookup
    # --------------------------------------------------------

    users_by_id = {
        user["user_id"]: user
        for user in users
    }

    # --------------------------------------------------------
    # Roster lookup
    # --------------------------------------------------------

    rosters_by_id = {
        str(roster["roster_id"]): roster
        for roster in rosters
    }

    # --------------------------------------------------------
    # Build roster data
    # --------------------------------------------------------

    roster_data = {}

    for roster in rosters:

        roster_id = int(
            roster["roster_id"]
        )

        user = users_by_id.get(
            roster.get("owner_id")
        )

        team_name = get_team_name(
            user,
            roster
        )

        player_ids = [
            str(x)
            for x in (
                roster.get("players")
                or []
            )
        ]

        starter_ids = [
            str(x)
            for x in (
                roster.get("starters")
                or []
            )
            if str(x) != "0"
        ]

        starter_set = set(
            starter_ids
        )

        bench_ids = [
            player_id
            for player_id in player_ids
            if player_id not in starter_set
        ]

        reserve_ids = [
            str(x)
            for x in (
                roster.get("reserve")
                or []
            )
        ]

        taxi_ids = [
            str(x)
            for x in (
                roster.get("taxi")
                or []
            )
        ]

        roster_data[str(roster_id)] = {

            "roster_id": roster_id,

            "owner_id": roster.get(
                "owner_id"
            ),

            "owner": clean_name(
                user.get("display_name")
                if user
                else ""
            ),

            "username": (
                user.get("username")
                if user
                else None
            ),

            "team_name": team_name,

            "record": get_record(
                roster.get("settings")
            ),

            "points": get_points(
                roster.get("settings")
            ),

            "waiver_position": (
                roster.get("settings", {})
                .get("waiver_position")
            ),

            "starters": [
                player_info(
                    player_id,
                    players
                )
                for player_id in starter_ids
            ],

            "bench": [
                player_info(
                    player_id,
                    players
                )
                for player_id in bench_ids
            ],

            "reserve": [
                player_info(
                    player_id,
                    players
                )
                for player_id in reserve_ids
            ],

            "taxi": [
                player_info(
                    player_id,
                    players
                )
                for player_id in taxi_ids
            ]
        }

    print(
        f"Built {len(roster_data)} rosters."
    )

    print()

    # ========================================================
    # WAIVER ORDER
    # ========================================================

    waiver_order = sorted(
        roster_data.values(),
        key=lambda r: (
            int(
                r["waiver_position"]
                or 999
            )
        )
    )

    waiver_order_output = [
        {
            "waiver_position":
                roster["waiver_position"],

            "roster_id":
                roster["roster_id"],

            "team_name":
                roster["team_name"],

            "owner":
                roster["owner"]
        }
        for roster in waiver_order
    ]

    # ========================================================
    # ROSTERED PLAYER IDs
    # ========================================================

    rostered_ids = set()

    for roster in rosters:

        for player_id in (
            roster.get("players")
            or []
        ):
            rostered_ids.add(
                str(player_id)
            )

        for player_id in (
            roster.get("reserve")
            or []
        ):
            rostered_ids.add(
                str(player_id)
            )

        for player_id in (
            roster.get("taxi")
            or []
        ):
            rostered_ids.add(
                str(player_id)
            )

    # ========================================================
    # AVAILABLE PLAYERS
    # ========================================================

    print(
        "Building waiver/free-agent pool..."
    )

    waiver_players = []

    for player_id, player in players.items():

        if str(player_id) in rostered_ids:
            continue

        if not is_useful_fantasy_player(
            player
        ):
            continue

        if not is_active_enough_for_waivers(
            player
        ):
            continue

        waiver_players.append(
            player_info(
                player_id,
                players
            )
        )

    waiver_players.sort(
        key=lambda p: (
            position_sort_value(
                p["position"]
            ),
            int(
                p["search_rank"]
                if p["search_rank"] is not None
                else 999999
            )
        )
    )

    waiver_by_position = {}

    for position in [
        "QB",
        "RB",
        "WR",
        "TE",
        "K",
        "DEF"
    ]:

        waiver_by_position[position] = [
            p
            for p in waiver_players
            if p["position"] == position
        ][:75]

    print(
        f"Found {len(waiver_players):,} usable "
        "waiver/free-agent players."
    )

    print()

    # ========================================================
    # TRANSACTIONS
    # ========================================================

    transaction_weeks = sorted(
        set([
            max(1, current_week - 2),
            max(1, current_week - 1),
            current_week
        ])
    )

    print(
        f"Loading transactions for weeks: "
        f"{', '.join(map(str, transaction_weeks))}"
    )

    transactions = []

    for week in transaction_weeks:

        try:

            raw_transactions = get_json(
                f"/league/{LEAGUE_ID}/transactions/{week}"
            )

        except Exception as error:

            print(
                f"  Week {week}: ERROR {error}"
            )

            continue

        print(
            f"  Week {week}: "
            f"{len(raw_transactions)} transactions"
        )

        for tx in raw_transactions:

            transactions.append(
                build_transaction_record(
                    tx,
                    week,
                    roster_data,
                    players
                )
            )

    transactions.sort(
        key=lambda tx: int(
            tx.get("created") or 0
        ),
        reverse=True
    )

    print()

    # ========================================================
    # MATCHUPS
    # ========================================================

    print("Loading matchups...")

    matchups = {}

    for week in transaction_weeks:

        try:

            matchups[str(week)] = get_json(
                f"/league/{LEAGUE_ID}/matchups/{week}"
            )

        except Exception as error:

            print(
                f"  Week {week}: ERROR {error}"
            )

            matchups[str(week)] = []

    print()

    # ========================================================
    # STANDINGS
    # ========================================================

    standings = sorted(
        roster_data.values(),
        key=lambda r: (
            -int(
                (
                    rosters_by_id[
                        str(r["roster_id"])
                    ]
                    .get("settings", {})
                    .get("wins", 0)
                    or 0
                )
            ),
            -float(
                r["points"]["pf"]
            )
        )
    )

    standings_output = []

    for index, roster in enumerate(
        standings,
        start=1
    ):

        standings_output.append({

            "rank": index,

            "roster_id":
                roster["roster_id"],

            "team_name":
                roster["team_name"],

            "owner":
                roster["owner"],

            "record":
                roster["record"],

            "points":
                roster["points"],

            "waiver_position":
                roster["waiver_position"]
        })

    # ========================================================
    # MY TEAM
    # ========================================================

    my_team = roster_data.get(
        str(MY_ROSTER_ID)
    )

    # ========================================================
    # SNAPSHOT
    # ========================================================

    generated_at = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    snapshot = {

        "snapshot_version": "3.0",

        "generated_at":
            generated_at,

        "source":
            "Sleeper public API",

        "league": {

            "league_id":
                league.get("league_id"),

            "name":
                league.get("name"),

            "season":
                season,

            "status":
                league.get("status"),

            "sport":
                league.get("sport"),

            "season_type":
                league.get("season_type"),

            "total_rosters":
                league.get("total_rosters"),

            "roster_positions":
                league.get("roster_positions"),

            "scoring_settings":
                league.get("scoring_settings"),

            "settings":
                league.get("settings"),

            "waiver_system":
                "waiver_priority",

            "faab_ignored":
                True
        },

        "nfl_state":
            nfl_state,

        "current_week":
            current_week,

        "my_team":
            my_team,

        "standings":
            standings_output,

        "waiver_order":
            waiver_order_output,

        "rosters":
            roster_data,

        "transactions":
            transactions,

        "matchups":
            matchups,

        "waiver_players":
            waiver_players,

        "waiver_by_position":
            waiver_by_position,

        "notes": [

            "Waiver priority is authoritative "
            "for this league.",

            "FAAB is intentionally ignored.",

            "NFL team assignments are taken "
            "directly from Sleeper.",

            "Available players are derived from "
            "players not currently rostered.",

            "Inactive and invalid database "
            "entries are filtered from the "
            "primary waiver pool.",

            "Trades are reconstructed using "
            "Sleeper's adds and drops mappings.",

            "Raw transaction data is preserved "
            "inside reconstructed trade records."
        ]
    }

    # ========================================================
    # SAVE JSON
    # ========================================================

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    week_string = str(
        current_week
    ).zfill(2)

    json_filename = (
        f"Sleeper_Snapshot_"
        f"{season}-W{week_string}.json"
    )

    md_filename = (
        f"Sleeper_Snapshot_"
        f"{season}-W{week_string}.md"
    )

    json_path = (
        OUTPUT_DIR /
        json_filename
    )

    md_path = (
        OUTPUT_DIR /
        md_filename
    )

    with open(
        json_path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            snapshot,
            file,
            indent=2,
            ensure_ascii=False
        )

    # ========================================================
    # MARKDOWN
    # ========================================================

    lines = []

    lines.append(
        f"# {league.get('name', 'Sleeper League')}"
    )

    lines.append("")

    lines.append(
        f"- League ID: `{LEAGUE_ID}`"
    )

    lines.append(
        f"- Season: {season}"
    )

    lines.append(
        f"- NFL week: {current_week}"
    )

    lines.append(
        f"- Status: {league.get('status')}"
    )

    lines.append(
        "- Scoring: PPR"
    )

    lines.append(
        "- Waiver system: **Waiver Priority**"
    )

    lines.append(
        f"- Snapshot generated: {generated_at}"
    )

    lines.append("")

    # ========================================================
    # MY TEAM
    # ========================================================

    lines.append("## My Team")
    lines.append("")

    if my_team:

        lines.append(
            f"**{md(my_team['team_name'])}**"
        )

        lines.append(
            f"- Owner: {md(my_team['owner'])}"
        )

        lines.append(
            f"- Record: {my_team['record']}"
        )

        lines.append(
            f"- Points: "
            f"{my_team['points']['pf']:.2f} PF / "
            f"{my_team['points']['pa']:.2f} PA"
        )

        lines.append(
            f"- Waiver priority: "
            f"**{my_team['waiver_position']}**"
        )

        lines.append("")

        lines.append("### Starters")
        lines.append("")

        for player in my_team["starters"]:

            lines.append(
                f"- {md(player_label(player['player_id'], players))}"
            )

        lines.append("")

        lines.append("### Bench")
        lines.append("")

        for player in my_team["bench"]:

            lines.append(
                f"- {md(player_label(player['player_id'], players))}"
            )

        if my_team["reserve"]:

            lines.append("")

            lines.append(
                "### IR / Reserve"
            )

            lines.append("")

            for player in my_team["reserve"]:

                lines.append(
                    f"- {md(player_label(player['player_id'], players))}"
                )

        if my_team["taxi"]:

            lines.append("")

            lines.append(
                "### Taxi"
            )

            lines.append("")

            for player in my_team["taxi"]:

                lines.append(
                    f"- {md(player_label(player['player_id'], players))}"
                )

        lines.append("")

    # ========================================================
    # STANDINGS
    # ========================================================

    lines.append("## Standings")
    lines.append("")

    lines.append(
        "| Rank | Team | Record | PF | PA | Waiver |"
    )

    lines.append(
        "|---:|---|---|---:|---:|---:|"
    )

    for standing in standings_output:

        lines.append(
            f"| {standing['rank']} | "
            f"{md(standing['team_name'])} | "
            f"{standing['record']} | "
            f"{standing['points']['pf']:.2f} | "
            f"{standing['points']['pa']:.2f} | "
            f"{standing['waiver_position']} |"
        )

    lines.append("")

    # ========================================================
    # WAIVER ORDER
    # ========================================================

    lines.append("## Waiver Order")
    lines.append("")

    for waiver in waiver_order_output:

        lines.append(
            f"{waiver['waiver_position']}. "
            f"**{md(waiver['team_name'])}** "
            f"({md(waiver['owner'])})"
        )

    lines.append("")

    # ========================================================
    # ALL ROSTERS
    # ========================================================

    lines.append("## Rosters")
    lines.append("")

    for roster in sorted(
        roster_data.values(),
        key=lambda r: r["roster_id"]
    ):

        mine = (
            " ⭐ MY TEAM"
            if roster["roster_id"]
            == MY_ROSTER_ID
            else ""
        )

        lines.append(
            f"### {md(roster['team_name'])}{mine}"
        )

        lines.append("")

        lines.append(
            f"- Owner: {md(roster['owner'])}"
        )

        lines.append(
            f"- Record: {roster['record']}"
        )

        lines.append(
            f"- Points: "
            f"{roster['points']['pf']:.2f} PF / "
            f"{roster['points']['pa']:.2f} PA"
        )

        lines.append(
            f"- Waiver priority: "
            f"{roster['waiver_position']}"
        )

        lines.append("")

        lines.append("**Starters**")
        lines.append("")

        for player in roster["starters"]:

            lines.append(
                f"- {md(player_label(player['player_id'], players))}"
            )

        lines.append("")

        lines.append("**Bench**")
        lines.append("")

        for player in roster["bench"]:

            lines.append(
                f"- {md(player_label(player['player_id'], players))}"
            )

        if roster["reserve"]:

            lines.append("")

            lines.append("**IR / Reserve**")
            lines.append("")

            for player in roster["reserve"]:

                lines.append(
                    f"- {md(player_label(player['player_id'], players))}"
                )

        if roster["taxi"]:

            lines.append("")

            lines.append("**Taxi**")
            lines.append("")

            for player in roster["taxi"]:

                lines.append(
                    f"- {md(player_label(player['player_id'], players))}"
                )

        lines.append("")

    # ========================================================
    # TRANSACTIONS
    # ========================================================

    lines.append("## Recent Transactions")
    lines.append("")

    if not transactions:

        lines.append(
            "- No transactions returned."
        )

    for tx in transactions[:100]:

        if tx["type"] == "trade":

            trade = tx["trade"]

            lines.append(
                f"### Week {tx['week']} | Trade"
            )

            lines.append("")

            if len(trade["sides"]) == 2:

                for side in trade["sides"]:

                    lines.append(
                        f"**{md(side['team_name'])}**"
                    )

                    if side["gave"]:

                        lines.append(
                            "Gave:"
                        )

                        for player in side["gave"]:

                            lines.append(
                                f"- {md(player['name'])}"
                            )

                    else:

                        lines.append(
                            "Gave: Nothing"
                        )

                    if side["received"]:

                        lines.append(
                            "Received:"
                        )

                        for player in side["received"]:

                            lines.append(
                                f"- {md(player['name'])}"
                            )

                    else:

                        lines.append(
                            "Received: Nothing"
                        )

                    lines.append("")

            else:

                team_names = ", ".join(
                    md(side["team_name"])
                   for side in trade["sides"]
                )

                lines.append(
                    f"Teams involved: {team_names}"
                )

                lines.append("")

            lines.append(
                f"Transaction ID: "
                f"`{tx['transaction_id']}`"
            )

            lines.append("")

        else:

            roster_names = [
                roster_data.get(
                    str(roster_id),
                    {}
                ).get(
                    "team_name",
                    f"Roster {roster_id}"
                )
                for roster_id
                in tx["roster_ids"]
            ]

            team_names = " / ".join(
                roster_names
            )

            line = (
                f"- Week {tx['week']} | "
                f"**{md(team_names)}** | "
                f"{tx['type']}"
            )

            if tx.get("adds"):

                adds = ", ".join(
                    p["name"]
                    for p in tx["adds"]
                )

                line += (
                    f" | ADD: {md(adds)}"
                )

            if tx.get("drops"):

                drops = ", ".join(
                    p["name"]
                    for p in tx["drops"]
                )

                line += (
                    f" | DROP: {md(drops)}"
                )

            lines.append(line)

    lines.append("")

    # ========================================================
    # WAIVERS
    # ========================================================

    lines.append(
        "## Available Waiver / Free-Agent Players"
    )

    lines.append("")

    lines.append(
        "_Primary waiver pool only. "
        "Inactive and invalid database entries "
        "are filtered out._"
    )

    lines.append("")

    for position in [
        "QB",
        "RB",
        "WR",
        "TE",
        "K",
        "DEF"
    ]:

        lines.append(
            f"### {position}"
        )

        lines.append("")

        players_for_position = (
            waiver_by_position[position]
        )

        if not players_for_position:

            lines.append(
                "- None found."
            )

        else:

            for player in players_for_position[:30]:

                line = (
                    f"- **{md(player['name'])}**"
                )

                if player["team"]:

                    line += (
                        f" ({player['team']})"
                    )

                if player["injury_status"]:

                    line += (
                        f" [{player['injury_status']}]"
                    )

                lines.append(line)

        lines.append("")

    # ========================================================
    # MATCHUPS
    # ========================================================

    lines.append("## Matchups")
    lines.append("")

    for week, games in matchups.items():

        lines.append(
            f"### Week {week}"
        )

        lines.append("")

        processed = set()

        for game in games or []:

            matchup_id = game.get(
                "matchup_id"
            )

            if matchup_id is None:
                continue

            if matchup_id in processed:
                continue

            teams = [
                x
                for x in games
                if x.get("matchup_id")
                == matchup_id
            ]

            if len(teams) >= 2:

                a = roster_data.get(
                    str(
                        teams[0]["roster_id"]
                    )
                )

                b = roster_data.get(
                    str(
                        teams[1]["roster_id"]
                    )
                )

                a_name = (
                    a["team_name"]
                    if a
                    else (
                        f"Roster "
                        f"{teams[0]['roster_id']}"
                    )
                )

                b_name = (
                    b["team_name"]
                    if b
                    else (
                        f"Roster "
                        f"{teams[1]['roster_id']}"
                    )
                )

                a_points = float(
                    teams[0].get(
                        "points",
                        0
                    )
                    or 0
                )

                b_points = float(
                    teams[1].get(
                        "points",
                        0
                    )
                    or 0
                )

                lines.append(
                    f"- {md(a_name)} "
                    f"({a_points:.2f}) vs "
                    f"{md(b_name)} "
                    f"({b_points:.2f})"
                )

            processed.add(
                matchup_id
            )

        lines.append("")

    # ========================================================
    # DATA NOTES
    # ========================================================

    lines.append("## Data Notes")
    lines.append("")

    for note in snapshot["notes"]:

        lines.append(
            f"- {note}"
        )

    lines.append("")

    # ========================================================
    # WRITE MARKDOWN
    # ========================================================

    with open(
        md_path,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(
            "\n".join(lines)
        )

    # ========================================================
    # SUMMARY
    # ========================================================

    trade_count = sum(
        1
        for tx in transactions
        if tx["type"] == "trade"
    )

    print("==========================================")
    print("SNAPSHOT COMPLETE")
    print("==========================================")
    print()
    print(f"League:       {league.get('name')}")
    print(f"Season:       {season}")
    print(f"Week:         {current_week}")
    print(f"Rosters:      {len(roster_data)}")
    print(
        f"Transactions: {len(transactions)}"
    )
    print(
        f"Trades:       {trade_count}"
    )
    print(
        f"Waiver pool:  {len(waiver_players)}"
    )
    print()
    print(f"JSON:")
    print(json_path)
    print()
    print(f"Markdown:")
    print(md_path)
    print()
    print("==========================================")


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        print()
        print("==========================================")
        print("ERROR")
        print("==========================================")
        print()
        print(
            f"{type(error).__name__}: {error}"
        )
        print()

        raise