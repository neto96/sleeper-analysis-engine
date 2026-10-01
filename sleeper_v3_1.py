import json
import os
import shutil
from datetime import datetime

import requests


# ============================================================
# CONFIG
# ============================================================

LEAGUE_ID = "1389736505374691328"
MY_ROSTER_ID = 3

API = "https://api.sleeper.app/v1"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_DIR = os.path.join(BASE_DIR, "snapshots")
HISTORY_DIR = os.path.join(SNAPSHOT_DIR, "history")

os.makedirs(SNAPSHOT_DIR, exist_ok=True)
os.makedirs(HISTORY_DIR, exist_ok=True)


# ============================================================
# API
# ============================================================

def get_json(url):
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def api_get(path):
    return get_json(f"{API}{path}")


# ============================================================
# HELPERS
# ============================================================

def clean_name(value):
    if value is None:
        return ""

    return " ".join(str(value).split()).strip()
    
def md(text):
    if text is None:
        return ""
    return str(text).replace("|", "\\|").replace("\n", " ")


def player_name(player_id, players):
    p = players.get(str(player_id), {})

    first = p.get("first_name") or ""
    last = p.get("last_name") or ""

    name = f"{first} {last}".strip()

    if name:
        return name

    full_name = p.get("full_name")
    if full_name:
        return full_name

    return f"Player {player_id}"


def player_info(player_id, players):
    p = players.get(str(player_id), {})

    return {
        "player_id": str(player_id),
        "name": player_name(player_id, players),
        "position": p.get("position"),
        "team": p.get("team"),
        "status": p.get("status"),
        "injury_status": p.get("injury_status"),
    }


def team_name_from_user(user):
    metadata = user.get("metadata") or {}

    return (
        metadata.get("team_name")
        or user.get("display_name")
        or user.get("username")
        or user.get("user_id")
        or "Unknown Team"
    )


def owner_name(user):
    return (
        user.get("display_name")
        or user.get("username")
        or user.get("user_id")
        or ""
    )


# ============================================================
# TRADE RECONSTRUCTION
# ============================================================

def reconstruct_trade(tx, roster_data, players):
    roster_ids = [int(x) for x in (tx.get("roster_ids") or [])]

    sides = {}

    for roster_id in roster_ids:
        roster = roster_data.get(str(roster_id))

        sides[roster_id] = {
            "roster_id": roster_id,
            "team_name": (
                clean_name(roster["team_name"])
                if roster
                else f"Roster {roster_id}"
            ),
            "owner": (
                roster["owner"]
                if roster
                else ""
            ),
            "gave": [],
            "received": [],
        }

    adds = tx.get("adds") or {}
    drops = tx.get("drops") or {}

    # Sleeper semantics confirmed from actual league data:
    #
    # adds[player_id] = roster_id receiving player
    # drops[player_id] = roster_id giving up player

    for player_id, receiving_roster in adds.items():
        receiving_roster = int(receiving_roster)

        if receiving_roster not in sides:
            sides[receiving_roster] = {
                "roster_id": receiving_roster,
                "team_name": f"Roster {receiving_roster}",
                "owner": "",
                "gave": [],
                "received": [],
            }

        sides[receiving_roster]["received"].append(
            player_info(player_id, players)
        )

    for player_id, giving_roster in drops.items():
        giving_roster = int(giving_roster)

        if giving_roster not in sides:
            sides[giving_roster] = {
                "roster_id": giving_roster,
                "team_name": f"Roster {giving_roster}",
                "owner": "",
                "gave": [],
                "received": [],
            }

        sides[giving_roster]["gave"].append(
            player_info(player_id, players)
        )

    side_list = list(sides.values())

    summary_parts = []

    for side in side_list:
        gave = ", ".join(x["name"] for x in side["gave"])
        received = ", ".join(x["name"] for x in side["received"])

        summary_parts.append(
            f"{side['team_name']}: "
            f"Gave [{gave}] "
            f"Received [{received}]"
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
        "summary": " | ".join(summary_parts),
        "raw_transaction": tx,
    }


# ============================================================
# TRANSACTIONS
# ============================================================

def build_transaction_record(tx, roster_data, players):
    tx_type = tx.get("type")

    if tx_type == "trade":
        return {
            "week": tx.get("week"),
            "type": "trade",
            "status": tx.get("status"),
            "created": tx.get("created"),
            "transaction_id": tx.get("transaction_id"),
            "trade": reconstruct_trade(
                tx,
                roster_data,
                players
            ),
        }

    adds = []

    for player_id, roster_id in (tx.get("adds") or {}).items():
        roster = roster_data.get(str(roster_id))

        adds.append({
            "player_id": str(player_id),
            "name": player_name(player_id, players),
            "roster_id": int(roster_id),
            "team_name": (
                clean_name(roster["team_name"])
                if roster
                else f"Roster {roster_id}"
            ),
        })

    drops = []

    for player_id, roster_id in (tx.get("drops") or {}).items():
        roster = roster_data.get(str(roster_id))

        drops.append({
            "player_id": str(player_id),
            "name": player_name(player_id, players),
            "roster_id": int(roster_id),
            "team_name": (
                clean_name(roster["team_name"])
                if roster
                else f"Roster {roster_id}"
            ),
        })

    return {
        "week": tx.get("week"),
        "type": tx_type,
        "status": tx.get("status"),
        "created": tx.get("created"),
        "transaction_id": tx.get("transaction_id"),
        "creator": tx.get("creator"),
        "adds": adds,
        "drops": drops,
        "draft_picks": tx.get("draft_picks") or [],
        "waiver_budget": tx.get("waiver_budget") or [],
    }


# ============================================================
# ROSTERS
# ============================================================

def build_rosters(rosters, users, players):
    roster_data = {}

    for roster in rosters:
        roster_id = int(roster["roster_id"])
        owner_id = roster.get("owner_id")

        user = users.get(str(owner_id), {})

        team_name = team_name_from_user(user)

        metadata = roster.get("metadata") or {}

        if metadata.get("team_name"):
            team_name = metadata["team_name"]

        settings = roster.get("settings") or {}

        record = {
            "roster_id": roster_id,
            "owner_id": owner_id,
            "owner": owner_name(user),
            "team_name": team_name,
            "record": {
                "wins": settings.get("wins", 0),
                "losses": settings.get("losses", 0),
                "ties": settings.get("ties", 0),
                "fpts": settings.get("fpts", 0),
                "fpts_against": settings.get("fpts_against", 0),
            },
            "waiver_priority": settings.get("waiver_position"),
            "players": [],
            "starters": [],
            "bench": [],
            "reserve": [],
            "taxi": [],
        }

        all_players = roster.get("players") or []
        starters = roster.get("starters") or []
        reserve = roster.get("reserve") or []
        taxi = roster.get("taxi") or []

        starter_ids = set(str(x) for x in starters)
        reserve_ids = set(str(x) for x in reserve)
        taxi_ids = set(str(x) for x in taxi)

        for pid in all_players:
            pid = str(pid)

            info = player_info(pid, players)

            record["players"].append(info)

            if pid in starter_ids:
                record["starters"].append(info)
            elif pid in reserve_ids:
                record["reserve"].append(info)
            elif pid in taxi_ids:
                record["taxi"].append(info)
            else:
                record["bench"].append(info)

        roster_data[str(roster_id)] = record

    return roster_data


# ============================================================
# WAIVERS
# ============================================================

def build_waiver_order(roster_data):
    entries = []

    for roster in roster_data.values():
        priority = roster.get("waiver_priority")

        if priority is None:
            continue

        entries.append({
            "priority": priority,
            "roster_id": roster["roster_id"],
            "team_name": clean_name(roster["team_name"]),
        })

    entries.sort(key=lambda x: x["priority"])

    return entries

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

def build_waiver_pool(players, roster_data):
    rostered_ids = set()

    for roster in roster_data.values():
        for player in roster["players"]:
            rostered_ids.add(str(player["player_id"]))

    pool = []

    for player_id, player in players.items():
        player_id = str(player_id)

        if player_id in rostered_ids:
            continue

        if not is_useful_fantasy_player(player):
            continue

        if not is_active_enough_for_waivers(player):
            continue

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

        pool.append({
            "player_id": player_id,
            "name": name,
            "position": player.get("position"),
            "team": player.get("team"),
            "status": player.get("status"),
            "injury_status": player.get("injury_status"),
            "search_rank": player.get("search_rank"),
        })

    def rank_key(player):
        rank = player.get("search_rank")

        if rank is None:
            return 999999

        try:
            return int(rank)
        except Exception:
            return 999999

    pool.sort(key=rank_key)

    return pool
    rostered_ids = set()

    for roster in roster_data.values():
        for pid in roster["players"]:
            rostered_ids.add(str(pid["player_id"]))

    pool = []

    for player_id, p in players.items():
        player_id = str(player_id)

        if player_id in rostered_ids:
            continue

        status = p.get("status")
        position = p.get("position")

        # Keep the original V3 filtering behavior.
        if status == "Inactive":
            continue

        if not position:
            continue

        if position not in {
            "QB",
            "RB",
            "WR",
            "TE",
            "K",
            "DEF",
        }:
            continue

        name = player_name(player_id, players)

        if not name:
            continue

        if name == "Player Invalid":
            continue

        # Exclude players with no meaningful NFL identity.
        nfl_team = p.get("team")

        if not nfl_team and status not in {
            "Active",
            "Injured Reserve",
        }:
            continue

        pool.append({
            "player_id": player_id,
            "name": name,
            "position": position,
            "team": nfl_team,
            "status": status,
            "injury_status": p.get("injury_status"),
            "search_rank": p.get("search_rank"),
        })

    def rank_key(x):
        rank = x.get("search_rank")

        if rank is None:
            return 999999

        try:
            return int(rank)
        except Exception:
            return 999999

    pool.sort(key=rank_key)

    return pool
    rostered_ids = set()

    for roster in roster_data.values():
        for pid in roster["players"]:
            rostered_ids.add(str(pid["player_id"]))

    pool = []

    for player_id, p in players.items():
        player_id = str(player_id)

        if player_id in rostered_ids:
            continue

        status = p.get("status")
        position = p.get("position")

        if status == "Inactive":
            continue

        if not position:
            continue

        if position not in {
            "QB",
            "RB",
            "WR",
            "TE",
            "K",
            "DEF",
        }:
            continue

        name = player_name(player_id, players)

        if not name or name == "Player Invalid":
            continue

        pool.append({
            "player_id": player_id,
            "name": name,
            "position": position,
            "team": p.get("team"),
            "status": status,
            "injury_status": p.get("injury_status"),
            "search_rank": p.get("search_rank"),
        })

    def rank_key(x):
        rank = x.get("search_rank")

        if rank is None:
            return 999999

        try:
            return int(rank)
        except Exception:
            return 999999

    pool.sort(key=rank_key)

    return pool


# ============================================================
# MATCHUPS
# ============================================================

def build_matchups(league_id, weeks, roster_data):
    result = {}

    for week in weeks:
        try:
            matchups = api_get(
                f"/league/{league_id}/matchups/{week}"
            )
        except Exception as e:
            result[str(week)] = {
                "error": str(e)
            }
            continue

        week_games = {}

        for matchup in matchups:
            matchup_id = matchup.get("matchup_id")

            if matchup_id is None:
                continue

            week_games.setdefault(
                str(matchup_id),
                []
            ).append(matchup)

        games = []

        for matchup_id, teams in week_games.items():
            if len(teams) != 2:
                continue

            a = teams[0]
            b = teams[1]

            ra = roster_data.get(
                str(a.get("roster_id")),
                {}
            )

            rb = roster_data.get(
                str(b.get("roster_id")),
                {}
            )

            games.append({
                "matchup_id": matchup_id,
                "team_a": {
                    "roster_id": a.get("roster_id"),
                    "team_name": ra.get(
                        "team_name",
                        f"Roster {a.get('roster_id')}"
                    ),
                    "points": a.get("points", 0),
                },
                "team_b": {
                    "roster_id": b.get("roster_id"),
                    "team_name": rb.get(
                        "team_name",
                        f"Roster {b.get('roster_id')}"
                    ),
                    "points": b.get("points", 0),
                },
            })

        result[str(week)] = games

    return result


# ============================================================
# STANDINGS
# ============================================================

def build_standings(roster_data):
    standings = []

    for roster in roster_data.values():
        record = roster["record"]

        standings.append({
            "roster_id": roster["roster_id"],
            "team_name": roster["team_name"],
            "owner": roster["owner"],
            "wins": record["wins"],
            "losses": record["losses"],
            "ties": record["ties"],
            "fpts": record["fpts"],
            "fpts_against": record["fpts_against"],
            "waiver_priority": roster["waiver_priority"],
        })

    standings.sort(
        key=lambda x: (
            -x["wins"],
            x["losses"],
            -float(x["fpts"] or 0),
        )
    )

    return standings


# ============================================================
# SNAPSHOT COMPARISON
# ============================================================

def player_map(roster):
    return {
        str(p["player_id"]): p
        for p in roster.get("players", [])
    }


def compare_rosters(previous, current):
    changes = []

    previous_rosters = previous.get("rosters", {})
    current_rosters = current.get("rosters", {})

    all_ids = sorted(
        set(previous_rosters.keys()) |
        set(current_rosters.keys()),
        key=lambda x: int(x)
    )

    for roster_id in all_ids:
        old = previous_rosters.get(roster_id)
        new = current_rosters.get(roster_id)

        if not old or not new:
            continue

        team_name = new.get(
            "team_name",
            old.get("team_name", f"Roster {roster_id}")
        )

        old_players = player_map(old)
        new_players = player_map(new)

        added_ids = sorted(
            set(new_players) - set(old_players),
            key=lambda x: new_players[x]["name"]
        )

        removed_ids = sorted(
            set(old_players) - set(new_players),
            key=lambda x: old_players[x]["name"]
        )

        starter_ids_old = {
            str(x["player_id"])
            for x in old.get("starters", [])
        }

        starter_ids_new = {
            str(x["player_id"])
            for x in new.get("starters", [])
        }

        became_starter = sorted(
            starter_ids_new - starter_ids_old,
            key=lambda x: new_players.get(
                x,
                {"name": x}
            )["name"]
        )

        became_bench = sorted(
            starter_ids_old - starter_ids_new,
            key=lambda x: old_players.get(
                x,
                {"name": x}
            )["name"]
        )

        old_priority = old.get("waiver_priority")
        new_priority = new.get("waiver_priority")

        if (
            added_ids
            or removed_ids
            or became_starter
            or became_bench
            or old_priority != new_priority
        ):
            changes.append({
                "roster_id": roster_id,
                "team_name": team_name,
                "added": [
                    new_players[x]
                    for x in added_ids
                ],
                "removed": [
                    old_players[x]
                    for x in removed_ids
                ],
                "became_starter": [
                    new_players[x]
                    for x in became_starter
                    if x in new_players
                ],
                "became_bench": [
                    old_players[x]
                    for x in became_bench
                    if x in old_players
                ],
                "waiver_before": old_priority,
                "waiver_after": new_priority,
            })

    return changes


def transaction_ids(snapshot):
    ids = set()

    for tx in snapshot.get("transactions", []):
        tx_id = tx.get("transaction_id")

        if tx_id:
            ids.add(str(tx_id))

    return ids



def find_new_transactions(previous, current):
    old_ids = transaction_ids(previous)

    new_transactions = []

    for tx in current.get("transactions", []):
        tx_id = tx.get("transaction_id")

        if tx_id and str(tx_id) not in old_ids:
            new_transactions.append(tx)

    return new_transactions

def classify_new_transactions(
    new_transactions,
    roster_data,
    players
    ):
    """
    Classify only transactions that are new since the
    previous snapshot.

    Returns:
        {
            "trades": [...],
            "waivers": [...],
            "adds": [...],
            "drops": [...],
            "other": [...]
        }
    """

    result = {
        "trades": [],
        "waivers": [],
        "adds": [],
        "drops": [],
        "other": [],
    }

    for tx in new_transactions:
        tx_type = str(
            tx.get("type") or ""
        ).lower()

        adds = tx.get("adds") or {}
        drops = tx.get("drops") or {}

        roster_ids = {
            int(x)
            for x in (tx.get("roster_ids") or [])
        }

        # ----------------------------------------------------
        # TRADE
        # ----------------------------------------------------
        #
        # A trade normally has multiple rosters involved.
        # We also check the presence of both adds and drops.
        #
        if (
            tx_type == "trade"
            or (
                len(roster_ids) >= 2
                and adds
                and drops
            )
        ):
            result["trades"].append(
                reconstruct_trade(
                    tx,
                    roster_data,
                    players
                )
            )

            continue

        # ----------------------------------------------------
        # WAIVER
        # ----------------------------------------------------
        if tx_type == "waiver":
            result["waivers"].append(tx)
            continue

        # FREE AGENT TRANSACTION
        if tx_type == "free_agent":
            result["adds"].append(tx)
            continue

        # FREE AGENT ADD
        if adds and not drops:
            result["adds"].append(tx)
            continue

        # DROP
        if drops and not adds:
            result["drops"].append(tx)
            continue

        # ----------------------------------------------------
        # OTHER
        # ----------------------------------------------------
        result["other"].append(tx)

    return result
def format_transaction_activity(
    classified,
    roster_data,
    players
    ):
    """
    Convert classified new transactions into
    human-readable activity records.
    """

    activity = []

    # --------------------------------------------------------
    # TRADES
    # --------------------------------------------------------
    for trade in classified["trades"]:
        activity.append({
            "type": "trade",
            "transaction_id": trade.get(
                "transaction_id"
            ),
            "created": trade.get("created"),
            "details": trade,
        })

    # --------------------------------------------------------
    # WAIVERS
    # --------------------------------------------------------
    for tx in classified["waivers"]:
        activity.append({
            "type": "waiver",
            "transaction_id": tx.get(
                "transaction_id"
            ),
            "created": tx.get("created"),
            "details": tx,
        })

    # --------------------------------------------------------
    # FREE AGENT ADDS
    # --------------------------------------------------------
    for tx in classified["adds"]:
        activity.append({
            "type": "add",
            "transaction_id": tx.get(
                "transaction_id"
            ),
            "created": tx.get("created"),
            "details": tx,
        })

    # --------------------------------------------------------
    # DROPS
    # --------------------------------------------------------
    for tx in classified["drops"]:
        activity.append({
            "type": "drop",
            "transaction_id": tx.get(
                "transaction_id"
            ),
            "created": tx.get("created"),
            "details": tx,
        })

    # --------------------------------------------------------
    # OTHER
    # --------------------------------------------------------
    for tx in classified["other"]:
        activity.append({
            "type": "other",
            "transaction_id": tx.get(
                "transaction_id"
            ),
            "created": tx.get("created"),
            "details": tx,
        })

    activity.sort(
        key=lambda x: x.get("created") or 0
    )

    return activity

def build_comparison(
    previous,
    current,
    roster_data,
    players
    ):
    if previous is None:
        return {
            "available": False,
            "reason": "No previous snapshot found."
        }

    roster_changes = compare_rosters(
        previous,
        current
    )

    new_transactions = find_new_transactions(
        previous,
        current
    )

    classified_activity = classify_new_transactions(
        new_transactions,
        roster_data,
        players
    )

    transaction_activity = format_transaction_activity(
        classified_activity,
        roster_data,
        players
    )

    return {
        "available": True,
        "previous_snapshot": previous.get(
            "snapshot_timestamp"
        ),
        "current_snapshot": current.get(
            "snapshot_timestamp"
        ),
        "roster_changes": roster_changes,
        "new_transactions": new_transactions,
        "activity": transaction_activity,
    }


# ============================================================
# MARKDOWN
# ============================================================

def transaction_markdown(transactions):
    lines = []

    for tx in transactions:
        week = tx.get("week")
        tx_type = tx.get("type")
        tx_id = tx.get("transaction_id")

        if tx_type == "trade":
            trade = tx["trade"]

            lines.append(
                f"### Week {week} | Trade"
            )
            lines.append("")

            for side in trade["sides"]:
                lines.append(
                    f"**{md(side['team_name'])}**"
                )
                lines.append("Gave:")

                if side["gave"]:
                    for p in side["gave"]:
                        lines.append(
                            f"- {md(p['name'])}"
                        )
                else:
                    lines.append("- None")

                lines.append("Received:")

                if side["received"]:
                    for p in side["received"]:
                        lines.append(
                            f"- {md(p['name'])}"
                        )
                else:
                    lines.append("- None")

                lines.append("")

            lines.append(
                f"Transaction ID: `{tx_id}`"
            )
            lines.append("")

        else:
            adds = tx.get("adds", [])
            drops = tx.get("drops", [])

            add_text = ", ".join(
                x["name"]
                for x in adds
            )

            drop_text = ", ".join(
                x["name"]
                for x in drops
            )

            team_names = set()

            for x in adds:
                team_names.add(x["team_name"])

            for x in drops:
                team_names.add(x["team_name"])

            team_name = (
                sorted(team_names)[0]
                if team_names
                else "Unknown Team"
            )

            action_parts = []

            if add_text:
                action_parts.append(
                    f"ADD: {add_text}"
                )

            if drop_text:
                action_parts.append(
                    f"DROP: {drop_text}"
                )

            lines.append(
                f"- Week {week} | "
                f"**{md(team_name)}** | "
                f"{tx_type} | "
                f"{' | '.join(action_parts)}"
            )

    return lines


def comparison_markdown(comparison):
    lines = []

    lines.append("## Changes Since Previous Snapshot")
    lines.append("")

    if not comparison.get("available"):
        lines.append(
            "_No previous snapshot was available for comparison._"
        )
        lines.append("")
        return lines

    activity = comparison.get(
        "activity",
        []
    )

    roster_changes = comparison.get(
        "roster_changes",
        []
    )

    if not activity and not roster_changes:
        lines.append(
            "**No changes detected.**"
        )
        lines.append("")
        return lines

    # ========================================================
    # NEW ACTIVITY
    # ========================================================

    if activity:
        lines.append("### New Activity")
        lines.append("")

        for item in activity:
            activity_type = item.get(
                "type",
                "other"
            )

            transaction_id = item.get(
                "transaction_id"
            )

            created = item.get(
                "created"
            )

            details = item.get(
                "details",
                {}
            )

            if activity_type == "trade":
                lines.append("#### TRADE")
                lines.append("")

                sides = details.get(
                    "sides",
                    []
                )

                for side in sides:
                    team_name = side.get(
                        "team_name",
                        "Unknown Team"
                    )

                    gave = ", ".join(
                        p.get("name", "Unknown Player")
                        for p in side.get("gave", [])
                    ) or "None"

                    received = ", ".join(
                        p.get("name", "Unknown Player")
                        for p in side.get("received", [])
                    ) or "None"

                    lines.append(
                        f"**{md(team_name)}**"
                    )

                    lines.append(
                        f"- Gave: {md(gave)}"
                    )

                    lines.append(
                        f"- Received: {md(received)}"
                    )

                    lines.append("")

                draft_picks = details.get(
                    "draft_picks",
                    []
                )

                if draft_picks:
                    lines.append(
                        "Draft picks involved:"
                    )

                    for pick in draft_picks:
                        lines.append(
                            f"- `{pick}`"
                        )

                    lines.append("")

            elif activity_type == "waiver":
                lines.append("#### WAIVER CLAIM")
                lines.append("")

                adds = details.get(
                    "adds",
                    {}
                )

                drops = details.get(
                    "drops",
                    {}
                )

                if adds:
                    for player_id, roster_id in adds.items():
                        lines.append(
                            f"- **Roster {roster_id}** "
                            f"received player `{player_id}`"
                        )

                if drops:
                    for player_id, roster_id in drops.items():
                        lines.append(
                            f"- **Roster {roster_id}** "
                            f"dropped player `{player_id}`"
                        )

                lines.append("")

            elif activity_type == "add":
                lines.append("#### FREE AGENT ACTIVITY")
                lines.append("")

                adds = details.get(
                    "adds",
                    []
                )

                drops = details.get(
                    "drops",
                    []
                )

                for player in adds:
                    team_name = player.get(
                        "team_name",
                        "Unknown Team"
                    )

                    player_name = player.get(
                        "name",
                        "Unknown Player"
                    )

                    lines.append(
                        f"- **{md(team_name)}** "
                        f"added **{md(player_name)}**"
                    )

                for player in drops:
                    team_name = player.get(
                        "team_name",
                        "Unknown Team"
                    )

                    player_name = player.get(
                        "name",
                        "Unknown Player"
                    )

                    lines.append(
                        f"- **{md(team_name)}** "
                        f"dropped **{md(player_name)}**"
                    )

                lines.append("")

            elif activity_type == "drop":
                lines.append("#### DROP")
                lines.append("")

                drops = details.get(
                    "drops",
                    {}
                )

                if drops:
                    for player_id, roster_id in drops.items():
                        lines.append(
                            f"- **Roster {roster_id}** "
                            f"dropped player `{player_id}`"
                        )

                lines.append("")

            else:
                lines.append(
                    f"#### {activity_type.upper()}"
                )
                lines.append("")

                lines.append(
                    "_Unclassified transaction._"
                )
                lines.append("")

            lines.append(
                f"Transaction ID: `{transaction_id}`"
            )

            if created:
                lines.append(
                    f"Created: `{created}`"
                )

            lines.append("")

    # ========================================================
    # ROSTER / LINEUP CHANGES
    # ========================================================

    if roster_changes:
        lines.append("### Roster & Lineup Changes")
        lines.append("")

        for change in roster_changes:
            lines.append(
                f"**{md(change['team_name'])}**"
            )

            if change["added"]:
                lines.append("Added to roster:")

                for player in change["added"]:
                    lines.append(
                        f"- + {md(player['name'])}"
                    )

            if change["removed"]:
                lines.append("Removed from roster:")

                for player in change["removed"]:
                    lines.append(
                        f"- - {md(player['name'])}"
                    )

            if change["became_starter"]:
                lines.append(
                    "Moved into starting lineup:"
                )

                for player in change["became_starter"]:
                    lines.append(
                        f"- START: {md(player['name'])}"
                    )

            if change["became_bench"]:
                lines.append(
                    "Moved out of starting lineup:"
                )

                for player in change["became_bench"]:
                    lines.append(
                        f"- BENCH: {md(player['name'])}"
                    )

            if (
                change["waiver_before"]
                != change["waiver_after"]
            ):
                lines.append(
                    f"- Waiver priority: "
                    f"{change['waiver_before']} → "
                    f"{change['waiver_after']}"
                )

            lines.append("")

    return lines


def build_markdown(snapshot):
    league = snapshot["league"]
    week = snapshot["week"]
    season = snapshot["season"]

    lines = []

    lines.append(
        f"# {league['name']}"
    )
    lines.append("")

    lines.append(
        f"**Season:** {season}"
    )
    lines.append(
        f"**NFL Week:** {week}"
    )
    lines.append(
        f"**Snapshot:** {snapshot['snapshot_timestamp']}"
    )
    lines.append("")

    # --------------------------------------------------------
    # COMPARISON
    # --------------------------------------------------------

    lines.extend(
        comparison_markdown(
            snapshot["comparison"]
        )
    )

    # --------------------------------------------------------
    # LEAGUE
    # --------------------------------------------------------

    lines.append("## League")
    lines.append("")

    lines.append(
        f"- Name: {md(league['name'])}"
    )
    lines.append(
        f"- League ID: `{league['league_id']}`"
    )
    lines.append(
        f"- Season: {league['season']}"
    )
    lines.append(
        f"- Status: {league.get('status')}"
    )
    lines.append("")

    # --------------------------------------------------------
    # STANDINGS
    # --------------------------------------------------------

    lines.append("## Standings")
    lines.append("")

    lines.append(
        "| Team | W | L | T | PF | PA | Waiver |"
    )
    lines.append(
        "|---|---:|---:|---:|---:|---:|---:|"
    )

    for team in snapshot["standings"]:
        lines.append(
            f"| {md(team['team_name'])} "
            f"| {team['wins']} "
            f"| {team['losses']} "
            f"| {team['ties']} "
            f"| {float(team['fpts'] or 0):.2f} "
            f"| {float(team['fpts_against'] or 0):.2f} "
            f"| {team['waiver_priority']} |"
        )

    lines.append("")

    # --------------------------------------------------------
    # ROSTERS
    # --------------------------------------------------------

    lines.append("## Rosters")
    lines.append("")

    for roster in snapshot["rosters"].values():
        marker = (
            " ⭐ MY TEAM"
            if roster["roster_id"] == MY_ROSTER_ID
            else ""
        )

        lines.append(
            f"### {md(roster['team_name'])}{marker}"
        )
        lines.append("")

        lines.append(
            f"- Owner: {md(roster['owner'])}"
        )
        lines.append(
            f"- Record: "
            f"{roster['record']['wins']}-"
            f"{roster['record']['losses']}"
        )
        lines.append(
            f"- Points: "
            f"{float(roster['record']['fpts'] or 0):.2f} PF / "
            f"{float(roster['record']['fpts_against'] or 0):.2f} PA"
        )
        lines.append(
            f"- Waiver priority: "
            f"{roster['waiver_priority']}"
        )
        lines.append("")

        lines.append("**Starters**")

        if roster["starters"]:
            for p in roster["starters"]:
                injury = (
                    f" ({p['injury_status']})"
                    if p.get("injury_status")
                    else ""
                )

                nfl_team = (
                    p.get("team")
                    or "FA"
                )

                lines.append(
                    f"- {md(p['name'])} "
                    f"{p.get('position') or ''}, "
                    f"{nfl_team}{injury}"
                )
        else:
            lines.append("- None")

        lines.append("")

        lines.append("**Bench**")

        if roster["bench"]:
            for p in roster["bench"]:
                injury = (
                    f" ({p['injury_status']})"
                    if p.get("injury_status")
                    else ""
                )

                nfl_team = (
                    p.get("team")
                    or "FA"
                )

                lines.append(
                    f"- {md(p['name'])} "
                    f"{p.get('position') or ''}, "
                    f"{nfl_team}{injury}"
                )
        else:
            lines.append("- None")

        lines.append("")

        if roster["reserve"]:
            lines.append("**Reserve / IR**")

            for p in roster["reserve"]:
                nfl_team = (
                    p.get("team")
                    or "FA"
                )

                lines.append(
                    f"- {md(p['name'])} "
                    f"{p.get('position') or ''}, "
                    f"{nfl_team}"
                )

            lines.append("")

        if roster["taxi"]:
            lines.append("**Taxi**")

            for p in roster["taxi"]:
                nfl_team = (
                    p.get("team")
                    or "FA"
                )

                lines.append(
                    f"- {md(p['name'])} "
                    f"{p.get('position') or ''}, "
                    f"{nfl_team}"
                )

            lines.append("")

    # --------------------------------------------------------
    # WAIVER ORDER
    # --------------------------------------------------------

    lines.append("## Waiver Priority")
    lines.append("")

    for entry in snapshot["waiver_order"]:
        lines.append(
            f"{entry['priority']}. "
            f"{md(entry['team_name'])}"
        )

    lines.append("")

    # --------------------------------------------------------
    # WAIVER POOL
    # --------------------------------------------------------

    lines.append("## Waiver / Free Agent Pool")
    lines.append("")

    lines.append(
        f"Total usable players: "
        f"{len(snapshot['waiver_pool'])}"
    )
    lines.append("")

    lines.append(
        "| Player | Pos | NFL | Status | Injury | Rank |"
    )
    lines.append(
        "|---|---|---|---|---|---:|"
    )

    for p in snapshot["waiver_pool"][:150]:
        lines.append(
            f"| {md(p['name'])} "
            f"| {p.get('position') or ''} "
            f"| {p.get('team') or 'FA'} "
            f"| {p.get('status') or ''} "
            f"| {p.get('injury_status') or ''} "
            f"| {p.get('search_rank') or ''} |"
        )

    lines.append("")

    # --------------------------------------------------------
    # TRANSACTIONS
    # --------------------------------------------------------

    lines.append("## Recent Transactions")
    lines.append("")

    lines.extend(
        transaction_markdown(
            snapshot["transactions"]
        )
    )

    # --------------------------------------------------------
    # MATCHUPS
    # --------------------------------------------------------

    lines.append("## Matchups")
    lines.append("")

    for week_number, games in snapshot["matchups"].items():
        lines.append(
            f"### Week {week_number}"
        )
        lines.append("")

        if isinstance(games, dict) and games.get("error"):
            lines.append(
                f"- Error: {games['error']}"
            )
            lines.append("")
            continue

        for game in games:
            a = game["team_a"]
            b = game["team_b"]

            lines.append(
                f"- {md(a['team_name'])} "
                f"({float(a['points'] or 0):.2f}) "
                f"vs "
                f"{md(b['team_name'])} "
                f"({float(b['points'] or 0):.2f})"
            )

        lines.append("")

    # --------------------------------------------------------
    # NOTES
    # --------------------------------------------------------

    lines.append("## Data Notes")
    lines.append("")
    lines.append(
        "- Waiver priority is authoritative for this league."
    )
    lines.append(
        "- FAAB fields are intentionally ignored."
    )
    lines.append(
        "- NFL team assignments come directly from Sleeper."
    )
    lines.append(
        "- Waiver/free-agent players are derived from "
        "players not currently rostered."
    )
    lines.append(
        "- Inactive and invalid database entries are "
        "filtered from the primary waiver pool."
    )
    lines.append(
        "- Player IDs and raw trade transactions are "
        "preserved in the JSON."
    )
    lines.append(
        "- This snapshot includes a comparison against "
        "the previous historical snapshot when available."
    )

    return "\n".join(lines)


# ============================================================
# FIND PREVIOUS SNAPSHOT
# ============================================================

def find_previous_snapshot():
    files = []

    for filename in os.listdir(HISTORY_DIR):
        if not filename.endswith(".json"):
            continue

        path = os.path.join(
            HISTORY_DIR,
            filename
        )

        files.append(path)

    if not files:
        return None

    files.sort(
        key=lambda p: os.path.getmtime(p),
        reverse=True
    )

    previous_path = files[0]

    try:
        with open(
            previous_path,
            "r",
            encoding="utf-8"
        ) as f:
            return json.load(f)
    except Exception:
        return None


# ============================================================
# MAIN
# ============================================================

def main():
    print("")
    print("==========================================")
    print("SLEEPER V3.1 SNAPSHOT")
    print("==========================================")
    print("")
    print("Pulling league data...")

    # --------------------------------------------------------
    # Core league data
    # --------------------------------------------------------

    league = api_get(
        f"/league/{LEAGUE_ID}"
    )

    users_raw = api_get(
        f"/league/{LEAGUE_ID}/users"
    )

    rosters_raw = api_get(
        f"/league/{LEAGUE_ID}/rosters"
    )

    nfl_state = api_get(
        "/state/nfl"
    )

    print("Pulling player database...")

    players = api_get(
        "/players/nfl"
    )

    users = {
        str(user["user_id"]): user
        for user in users_raw
    }

    roster_data = build_rosters(
        rosters_raw,
        users,
        players
    )

    waiver_order = build_waiver_order(
        roster_data
    )

    waiver_pool = build_waiver_pool(
        players,
        roster_data
    )

    # --------------------------------------------------------
    # Week information
    # --------------------------------------------------------

    current_week = int(
        nfl_state.get("week")
        or league.get("settings", {}).get("leg")
        or 1
    )

    season = str(
        nfl_state.get("season")
        or league.get("season")
    )

    weeks = sorted(
        set([
            max(1, current_week - 2),
            max(1, current_week - 1),
            current_week,
        ])
    )

    # --------------------------------------------------------
    # Transactions
    # --------------------------------------------------------

    print("Pulling transactions...")

    all_transactions = []

    for week in weeks:
        try:
            transactions = api_get(
                f"/league/{LEAGUE_ID}/transactions/{week}"
            )

            for tx in transactions:
                record = build_transaction_record(
                    tx,
                    roster_data,
                    players
                )

                all_transactions.append(record)

        except Exception as e:
            print(
                f"Warning: could not retrieve "
                f"transactions for week {week}: {e}"
            )

    # newest first
    all_transactions.sort(
        key=lambda x: (
            x.get("created") or 0
        ),
        reverse=True
    )

    # --------------------------------------------------------
    # Matchups
    # --------------------------------------------------------

    print("Pulling matchups...")

    matchups = build_matchups(
        LEAGUE_ID,
        weeks,
        roster_data
    )

    # --------------------------------------------------------
    # Standings
    # --------------------------------------------------------

    standings = build_standings(
        roster_data
    )

    # --------------------------------------------------------
    # Timestamp
    # --------------------------------------------------------

    now = datetime.now()

    timestamp = now.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    timestamp_file = now.strftime(
        "%Y-%m-%d_%H%M%S"
    )

    # --------------------------------------------------------
    # Build snapshot
    # --------------------------------------------------------

    snapshot = {
        "snapshot_timestamp": timestamp,
        "snapshot_version": "3.1",

        "league": {
            "league_id": LEAGUE_ID,
            "name": league.get(
                "name",
                "Unknown League"
            ),
            "season": season,
            "status": league.get("status"),
            "settings": league.get("settings") or {},
            "roster_positions": (
                league.get("roster_positions") or []
            ),
            "scoring_settings": (
                league.get("scoring_settings") or {}
            ),
        },

        "season": season,
        "week": current_week,

        "nfl_state": nfl_state,

        "users": users,

        "rosters": roster_data,

        "waiver_order": waiver_order,

        "waiver_pool": waiver_pool,

        "transactions": all_transactions,

        "matchups": matchups,

        "standings": standings,
        
        "comparison": None,
    }

    # --------------------------------------------------------
    # Compare against previous snapshot
    # --------------------------------------------------------

    print("Checking for changes...")

    previous_snapshot = find_previous_snapshot()

    comparison = build_comparison(
        previous_snapshot,
        snapshot,
        roster_data,
        players
    )

    snapshot["comparison"] = comparison

    # --------------------------------------------------------
    # File paths
    # --------------------------------------------------------

    weekly_json = os.path.join(
        SNAPSHOT_DIR,
        f"Sleeper_Snapshot_{season}-W{current_week:02d}.json"
    )

    weekly_md = os.path.join(
        SNAPSHOT_DIR,
        f"Sleeper_Snapshot_{season}-W{current_week:02d}.md"
    )

    history_json = os.path.join(
        HISTORY_DIR,
        f"Sleeper_{timestamp_file}.json"
    )

    latest_json = os.path.join(
        SNAPSHOT_DIR,
        "latest.json"
    )

    latest_md = os.path.join(
        SNAPSHOT_DIR,
        "latest.md"
    )

    # --------------------------------------------------------
    # Markdown
    # --------------------------------------------------------

    markdown = build_markdown(
        snapshot
    )

    # --------------------------------------------------------
    # Save JSON
    # --------------------------------------------------------

    with open(
        history_json,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            snapshot,
            f,
            indent=2,
            ensure_ascii=False
        )

    with open(
        weekly_json,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            snapshot,
            f,
            indent=2,
            ensure_ascii=False
        )

    with open(
        latest_json,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            snapshot,
            f,
            indent=2,
            ensure_ascii=False
        )

    # --------------------------------------------------------
    # Save Markdown
    # --------------------------------------------------------

    with open(
        weekly_md,
        "w",
        encoding="utf-8"
    ) as f:
        f.write(markdown)

    with open(
        latest_md,
        "w",
        encoding="utf-8"
    ) as f:
        f.write(markdown)

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    trade_count = sum(
        1
        for tx in all_transactions
        if tx.get("type") == "trade"
    )

    if comparison.get("available"):
        new_tx_count = len(
            comparison.get(
                "new_transactions",
                []
            )
        )

        roster_change_count = len(
            comparison.get(
                "roster_changes",
                []
            )
        )
    else:
        new_tx_count = 0
        roster_change_count = 0

    print("")
    print("==========================================")
    print("SNAPSHOT COMPLETE")
    print("==========================================")
    print("")
    print(
        f"League:              "
        f"{league.get('name')}"
    )
    print(
        f"Season:              "
        f"{season}"
    )
    print(
        f"Week:                "
        f"{current_week}"
    )
    print(
        f"Rosters:             "
        f"{len(roster_data)}"
    )
    print(
        f"Transactions:        "
        f"{len(all_transactions)}"
    )
    print(
        f"Trades:              "
        f"{trade_count}"
    )
    print(
        f"Waiver pool:         "
        f"{len(waiver_pool)}"
    )
    print("")
    print(
        f"New transactions:    "
        f"{new_tx_count}"
    )
    print(
        f"Rosters changed:     "
        f"{roster_change_count}"
    )
    print("")
    print("Weekly JSON:")
    print(weekly_json)
    print("")
    print("Weekly Markdown:")
    print(weekly_md)
    print("")
    print("History JSON:")
    print(history_json)
    print("")
    print("Latest JSON:")
    print(latest_json)
    print("")
    print("Latest Markdown:")
    print(latest_md)
    print("")
    print("==========================================")
    print("")


if __name__ == "__main__":
    main()