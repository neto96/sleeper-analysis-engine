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

PLAYER_CACHE_FILE = os.path.join(
    SNAPSHOT_DIR,
    "players_nfl_cache.json"
)

PLAYER_CACHE_MAX_AGE = 24 * 60 * 60

# ============================================================
# API
# ============================================================

def get_json(url):
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def api_get(path):
    return get_json(f"{API}{path}")

def get_players_cached():
    now = datetime.now().timestamp()

    if os.path.exists(PLAYER_CACHE_FILE):
        cache_age = (
            now - os.path.getmtime(PLAYER_CACHE_FILE)
        )

        if cache_age < PLAYER_CACHE_MAX_AGE:
            with open(
                PLAYER_CACHE_FILE,
                "r",
                encoding="utf-8"
            ) as f:
                players = json.load(f)

            age_hours = cache_age / 3600

            print(
                f"Using cached player database "
                f"({age_hours:.1f} hours old)."
            )

            return players

        print(
            "Player database cache is older than "
            "24 hours. Refreshing..."
        )

    else:
        print(
            "No player database cache found. "
            "Downloading from Sleeper..."
        )

    players = api_get(
        "/players/nfl"
    )

    with open(
        PLAYER_CACHE_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            players,
            f,
            indent=2,
            ensure_ascii=False
        )

    print(
        "Player database downloaded and cached."
    )

    return players
# HELPERS
# ============================================================
# ============================================================

def build_league_position_analysis(
    fantasy_analysis
    ):

    positions = [
        "QB",
        "RB",
        "WR",
        "TE",
        "K",
        "DEF"
    ]

    league_analysis = {}

    roster_demands = {}
    direct_demand_by_position = {position: 0 for position in positions}
    flex_demand_by_code = {}
    eligible_flex_demand_by_position = {position: 0 for position in positions}
    total_configured_starting_slots = 0
    total_supported_starting_slots = 0
    unsupported_slot_counts = {}

    for roster_id, team in fantasy_analysis["teams"].items():
        roster_configuration = team.get(
            "roster_configuration",
            fantasy_analysis.get("roster_configuration", {}),
        )
        configured_slots = expand_roster_slots(roster_configuration)
        direct_demand = {position: 0 for position in positions}
        flex_slots = {}
        unsupported_slots = {}
        supported_slot_count = 0
        configured_slot_count = 0

        for slot in configured_slots:
            if slot["slot_type"] == "nonstarter":
                continue
            configured_slot_count += 1

            if (
                slot["slot_type"] == "unknown"
                or not slot["supported_by_analyzer"]
            ):
                slot_code = slot["slot_code"]
                unsupported_slots[slot_code] = (
                    unsupported_slots.get(slot_code, 0) + 1
                )
                unsupported_slot_counts[slot_code] = (
                    unsupported_slot_counts.get(slot_code, 0) + 1
                )
                continue

            if slot["slot_type"] == "direct":
                slot_code = slot["slot_code"]
                if slot_code in direct_demand:
                    direct_demand[slot_code] += 1
                    direct_demand_by_position[slot_code] += 1
                    supported_slot_count += 1
            elif slot["slot_type"] == "flex":
                slot_code = slot["slot_code"]
                flex_slots.setdefault(slot_code, {
                    "count": 0,
                    "eligible_positions": slot["eligible_positions"].copy(),
                })
                flex_slots[slot_code]["count"] += 1
                supported_slot_count += 1

        for slot_code, flex_slot in flex_slots.items():
            aggregate = flex_demand_by_code.setdefault(slot_code, {
                "count": 0,
                "eligible_positions": flex_slot["eligible_positions"].copy(),
            })
            aggregate["count"] += flex_slot["count"]
            for position in flex_slot["eligible_positions"]:
                if position in eligible_flex_demand_by_position:
                    eligible_flex_demand_by_position[position] += (
                        flex_slot["count"]
                    )

        total_configured_starting_slots += configured_slot_count
        total_supported_starting_slots += supported_slot_count
        roster_demands[roster_id] = {
            "direct_slots": direct_demand,
            "flex_slots": flex_slots,
            "configured_starting_slots": configured_slot_count,
            "supported_starting_slots": supported_slot_count,
            "unsupported_slots": dict(sorted(unsupported_slots.items())),
        }

    league_analysis["configuration_demand"] = {
        "direct_demand_by_position": direct_demand_by_position,
        "flex_demand_by_slot_code": dict(sorted(flex_demand_by_code.items())),
        "eligible_flex_slot_instances_by_position": (
            eligible_flex_demand_by_position
        ),
        "total_configured_starting_slots": total_configured_starting_slots,
        "supported_starting_slots": total_supported_starting_slots,
        "unsupported_slot_counts": dict(sorted(unsupported_slot_counts.items())),
        "by_roster": roster_demands,
    }

    for position in positions:

        team_counts = []

        for roster_id, team in fantasy_analysis[
            "teams"
        ].items():

            summary = team[
                "position_summary"
            ][position]

            team_counts.append({
                "roster_id": roster_id,
                "team_name": team[
                    "team_name"
                ],
                "total": summary[
                    "total"
                ],
                "starters": summary[
                    "starters"
                ],
                "bench": summary[
                    "bench"
                ],
                "depth_score": summary[
                    "depth_score"
                ],
                "meaningful_players": summary[
                    "meaningful_players"
                ]
            })

        if not team_counts:
            continue

        totals = [
            team["total"]
            for team in team_counts
        ]

        depth_scores = [
            team["depth_score"]
            for team in team_counts
        ]

        meaningful_counts = [
            team["meaningful_players"]
            for team in team_counts
        ]

        sorted_totals = sorted(
            totals
        )

        sorted_depth = sorted(
            depth_scores
        )

        sorted_meaningful = sorted(
            meaningful_counts
        )

        count = len(sorted_totals)

        if count % 2 == 0:

            median_total = (
                sorted_totals[count // 2 - 1]
                + sorted_totals[count // 2]
            ) / 2

            median_depth = (
                sorted_depth[count // 2 - 1]
                + sorted_depth[count // 2]
            ) / 2

            median_meaningful = (
                sorted_meaningful[count // 2 - 1]
                + sorted_meaningful[count // 2]
            ) / 2

        else:

            median_total = (
                sorted_totals[count // 2]
            )

            median_depth = (
                sorted_depth[count // 2]
            )

            median_meaningful = (
                sorted_meaningful[count // 2]
            )

        league_analysis[position] = {
            "teams": team_counts,

            "configured_direct_demand": direct_demand_by_position[position],
            # This is shared capacity: values across positions overlap and
            # must not be summed as independent positional requirements.
            "eligible_flex_slot_instances": (
                eligible_flex_demand_by_position[position]
            ),

            "average_total": round(
                sum(totals) / count,
                2
            ),

            "median_total": median_total,

            "minimum_total": min(
                totals
            ),

            "maximum_total": max(
                totals
            ),

            "average_depth_score": round(
                sum(depth_scores) / count,
                2
            ),

            "median_depth_score": median_depth,

            "minimum_depth_score": min(
                depth_scores
            ),

            "maximum_depth_score": max(
                depth_scores
            ),

            "average_meaningful_players": round(
                sum(meaningful_counts) / count,
                2
            ),

            "median_meaningful_players":
                median_meaningful,

            "minimum_meaningful_players":
                min(meaningful_counts),

            "maximum_meaningful_players":
                max(meaningful_counts)
        }

    # ------------------------------------------
    # FLEX ANALYSIS
    # ------------------------------------------

    flex_team_counts = []

    for roster_id, team in fantasy_analysis["teams"].items():
        demand = roster_demands[roster_id]
        flex_positions = sorted({
            position
            for flex_slot in demand["flex_slots"].values()
            for position in flex_slot["eligible_positions"]
        })
        meaningful_tiers = {"elite", "strong", "useful"}
        meaningful_players_by_position = {
            position: [
                player
                for player in team.get("positions", {}).get(position, [])
                if player.get("fantasy_value_tier") in meaningful_tiers
            ]
            for position in positions
        }
        direct_player_ids = set()
        for position, required in demand["direct_slots"].items():
            for index, player in enumerate(
                meaningful_players_by_position.get(position, [])[:required]
            ):
                player_id = player.get("player_id")
                direct_player_ids.add(
                    ("player", str(player_id))
                    if player_id is not None
                    else ("missing_id", position, index)
                )

        meaningful_flex_player_ids = set()

        for position in flex_positions:
            for index, player in enumerate(
                meaningful_players_by_position.get(position, [])
            ):
                player_id = player.get("player_id")
                candidate_id = (
                    ("player", str(player_id))
                    if player_id is not None
                    else ("missing_id", position, index)
                )
                if candidate_id not in direct_player_ids:
                    meaningful_flex_player_ids.add(candidate_id)

        flex_meaningful = len(meaningful_flex_player_ids)
        configured_flex_slots = sum(
            slot["count"] for slot in demand["flex_slots"].values()
        )

        flex_team_counts.append({
            "roster_id": roster_id,
            "team_name": team[
                "team_name"
            ],
            "meaningful_flex_players": flex_meaningful,
            "configured_flex_slots": configured_flex_slots,
        })

    if flex_team_counts:

        flex_values = [
            team[
                "meaningful_flex_players"
            ]
            for team in flex_team_counts
        ]

        sorted_flex = sorted(
            flex_values
        )

        flex_count = len(
            sorted_flex
        )

        if flex_count % 2 == 0:

            median_flex = (
                sorted_flex[
                    flex_count // 2 - 1
                ]
                + sorted_flex[
                    flex_count // 2
                ]
            ) / 2

        else:

            median_flex = (
                sorted_flex[
                    flex_count // 2
                ]
            )

        league_analysis["FLEX"] = {
            "teams": flex_team_counts,

            "configured_slots": sum(
                item["count"] for item in flex_demand_by_code.values()
            ),
            "slot_counts_by_type": {
                slot_code: data["count"]
                for slot_code, data in sorted(flex_demand_by_code.items())
            },
            "eligible_positions_by_type": {
                slot_code: data["eligible_positions"]
                for slot_code, data in sorted(flex_demand_by_code.items())
            },

            "average_meaningful_players":
                round(
                    sum(flex_values)
                    / flex_count,
                    2
                ),

            "median_meaningful_players":
                median_flex,

            "minimum_meaningful_players":
                min(flex_values),

            "maximum_meaningful_players":
                max(flex_values)
        }

    return league_analysis

def get_position_slot_requirements(position, configured_slots):
    """Return direct demand and shared FLEX types eligible for a position."""
    direct_required = sum(
        1
        for slot in configured_slots
        if slot["slot_type"] == "direct"
        and slot["slot_code"] == position
        and slot["supported_by_analyzer"]
    )
    flex_slot_codes = sorted({
        slot["slot_code"]
        for slot in configured_slots
        if slot["slot_type"] == "flex"
        and slot["supported_by_analyzer"]
        and position in slot["eligible_positions"]
    })

    return {
        "direct_required": direct_required,
        "flex_slot_codes": flex_slot_codes,
    }


def classify_position_need(
    position,
    team_summary,
    league_position_analysis,
    configured_slots,
    ):

    meaningful = team_summary.get(
        "meaningful_players",
        0
    )

    depth_score = team_summary.get(
        "depth_score",
        0
    )

    starters = team_summary.get(
        "starters",
        0
    )

    position_data = league_position_analysis.get(
        position
    )

    if not position_data:
        return {
            "need": "unknown",
            "reason": "No league comparison available."
        }

    median_depth = position_data.get(
        "median_depth_score",
        0
    )

    median_meaningful = position_data.get(
        "median_meaningful_players",
        0
    )

    slot_requirements = get_position_slot_requirements(
        position,
        configured_slots,
    )
    required_players = slot_requirements["direct_required"]

    starting_shortage = max(
        required_players - starters,
        0
    )

    depth_difference = (
        depth_score - median_depth
    )

    meaningful_difference = (
        meaningful - median_meaningful
    )

    # ------------------------------------------
    # ACTUAL STARTING SHORTAGE
    # ------------------------------------------

    if starting_shortage > 0:
        return {
            "need": "high",
            "reason": (
                f"Only {starters} starting "
                f"{position} player(s) for "
                f"{required_players} required."
            ),
            "depth_difference": depth_difference,
            "meaningful_difference":
                meaningful_difference
        }

    # ------------------------------------------
    # SEVERE DEPTH DEFICIT
    # ------------------------------------------

    if (
        depth_score < median_depth
        and meaningful < median_meaningful
    ):
        return {
            "need": "moderate",
            "reason": (
                f"{position} depth is below the "
                f"league median in both quality "
                f"and meaningful player count."
            ),
            "depth_difference": depth_difference,
            "meaningful_difference":
                meaningful_difference
        }
        
    # ------------------------------------------
    # MEANINGFUL PLAYERS BELOW MEDIAN
    # ------------------------------------------

    if meaningful < median_meaningful:
        return {
            "need": "moderate",
            "reason": (
                f"{position} has fewer meaningful "
                f"players than the league median."
            ),
            "depth_difference": depth_difference,
            "meaningful_difference":
                meaningful_difference
        }

    # ------------------------------------------
    # DEPTH SCORE BELOW MEDIAN
    # ------------------------------------------

    if depth_score < median_depth:
        return {
            "need": "moderate",
            "reason": (
                f"{position} depth is below "
                f"the league median."
            ),
            "depth_difference": depth_difference,
            "meaningful_difference":
                meaningful_difference
        }

    # ------------------------------------------
    # STRONG DEPTH
    # ------------------------------------------

    if (
        depth_score > median_depth
        and meaningful > median_meaningful
    ):
        return {
            "need": "low",
            "reason": (
                f"{position} depth and meaningful "
                f"player count are above the "
                f"league median."
            ),
            "depth_difference": depth_difference,
            "meaningful_difference":
                meaningful_difference
        }

    # ------------------------------------------
    # AROUND LEAGUE MEDIAN
    # ------------------------------------------

    return {
        "need": "moderate",
        "reason": (
            f"{position} depth is around "
            f"the league median."
        ),
        "depth_difference": depth_difference,
        "meaningful_difference":
            meaningful_difference
    }
def calculate_optimal_lineup(positions, roster_configuration):
    """Find the highest-scoring legal QB/RB/WR/TE lineup for configured slots.

    K, DEF, and IDP slots remain outside this offensive optimizer. Slot
    eligibility and counts come from the shared normalized slot expansion.
    """
    supported_positions = ["QB", "RB", "WR", "TE"]

    tier_score = {
        "elite": 5,
        "strong": 4,
        "useful": 3,
        "fringe": 2,
        "deep_waiver": 1,
        "unknown": 0
    }

    def player_score(player):
        if player.get("status") == "Inactive":
            return -1

        if player.get("injury_status") == "IR":
            return -1

        return (
            tier_score.get(
                player.get("fantasy_value_tier"),
                0
            ) * 100
            + player.get("importance_score", 0)
        )

    best_lineup = {
        "QB": [],
        "RB": [],
        "WR": [],
        "TE": [],
        "FLEX": []
    }
    slots = []

    for configured_slot in expand_roster_slots(roster_configuration):
        if configured_slot["slot_type"] not in {"direct", "flex"}:
            continue

        eligible_positions = [
            position
            for position in configured_slot["eligible_positions"]
            if position in supported_positions
        ]
        if not eligible_positions:
            continue

        slot_code = configured_slot["slot_code"]
        if configured_slot["is_flex"]:
            best_lineup.setdefault(slot_code, [])

        slots.append({
            "lineup_position": slot_code,
            "eligible_positions": eligible_positions,
            "is_flex": configured_slot["is_flex"],
        })

    candidates = []
    seen_player_ids = set()

    for position in supported_positions:
        for player in positions.get(position, []):
            player_id = player.get("player_id")
            if player_id is None:
                continue

            # build_fantasy_analysis stores string IDs and keeps position in
            # the containing group; preserve those V3.2 data-model semantics.
            player_key = player_id
            if player_key in seen_player_ids:
                continue

            # V3.2 annotated candidates from the position-group key.
            actual_position = position
            if actual_position not in supported_positions:
                continue

            score = player_score(player)
            if score < 0:
                continue

            seen_player_ids.add(player_key)
            candidate = player.copy()
            candidate["position"] = actual_position
            candidates.append({
                "player_id": player_key,
                "position": actual_position,
                "score": score,
                "order": len(candidates),
                "player": candidate,
            })

    candidates_by_slot = []
    legacy_flex_priority = {"WR": 0, "RB": 1, "TE": 2}

    for slot in slots:
        eligible_positions = slot["eligible_positions"]
        if slot["is_flex"] and slot["lineup_position"] == "FLEX":
            position_priority = legacy_flex_priority
        else:
            position_priority = {
                position: index
                for index, position in enumerate(eligible_positions)
            }

        eligible_candidates = [
            candidate
            for candidate in candidates
            if candidate["position"] in eligible_positions
        ]
        eligible_candidates.sort(
            key=lambda candidate: (
                -candidate["score"],
                position_priority.get(candidate["position"], 99),
                candidate["order"],
            )
        )
        candidates_by_slot.append(eligible_candidates)

    best_score = -1
    best_filled_slots = -1
    best_assignment = None

    # This exact search is intentionally sized for current fantasy rosters;
    # its worst-case complexity is exponential in the number of slots.
    def search(slot_index, total_score, used_player_ids, assignment, filled_slots):
        nonlocal best_score, best_filled_slots, best_assignment

        if slot_index == len(slots):
            if (
                total_score > best_score
                or (
                    total_score == best_score
                    and filled_slots > best_filled_slots
                )
            ):
                best_score = total_score
                best_filled_slots = filled_slots
                best_assignment = assignment.copy()
            return

        upper_score = total_score
        upper_filled_slots = filled_slots
        for remaining_candidates in candidates_by_slot[slot_index:]:
            available_scores = [
                candidate["score"]
                for candidate in remaining_candidates
                if candidate["player_id"] not in used_player_ids
            ]
            if available_scores:
                upper_score += max(available_scores)
                upper_filled_slots += 1

        if best_assignment is not None and (
            upper_score < best_score
            or (
                upper_score == best_score
                and upper_filled_slots <= best_filled_slots
            )
        ):
            return

        for candidate in candidates_by_slot[slot_index]:
            player_id = candidate["player_id"]
            if player_id in used_player_ids:
                continue

            used_player_ids.add(player_id)
            assignment.append(candidate)
            search(
                slot_index + 1,
                total_score + candidate["score"],
                used_player_ids,
                assignment,
                filled_slots + 1,
            )
            assignment.pop()
            used_player_ids.remove(player_id)

        assignment.append(None)
        search(
            slot_index + 1,
            total_score,
            used_player_ids,
            assignment,
            filled_slots,
        )
        assignment.pop()

    search(0, 0, set(), [], 0)

    if best_assignment is not None:
        for slot, candidate in zip(slots, best_assignment):
            if candidate is not None:
                best_lineup[slot["lineup_position"]].append(
                    candidate["player"].copy()
                )

    return best_lineup

def classify_starting_depth(
    position,
    team_summary,
    positions,
    optimal_lineup,
    configured_slots,
    ):
    slot_requirements = get_position_slot_requirements(
        position,
        configured_slots,
    )
    required_players = slot_requirements["direct_required"]

    starters = team_summary.get(
        "starters",
        0
    )

    meaningful = team_summary.get(
        "meaningful_players",
        0
    )

    direct_shortage = max(
        required_players - starters,
        0
    )

    direct_surplus = max(
        starters - required_players,
        0
    )

    position_ids = {
        player.get("player_id")
        for player in positions.get(position, [])
    }
    flex_player_ids = set()
    for slot_code in slot_requirements["flex_slot_codes"]:
        for player in optimal_lineup.get(slot_code, []):
            player_id = player.get("player_id")
            if (
                player_id in position_ids
                and player.get("position", position) == position
            ):
                flex_player_ids.add(player_id)
    flex_available = len(flex_player_ids)

    if required_players == 0 and flex_available == 0:
        starting_depth = "adequate"

        return {
            "required": required_players,
            "starters": starters,
            "direct_shortage": direct_shortage,
            "direct_surplus": direct_surplus,
            "meaningful_players": meaningful,
            "flex_available": flex_available,
            "starting_depth": starting_depth
        }

    if position == "QB":

        effective_required = required_players + flex_available
        if meaningful < effective_required:
            starting_depth = "short"

        elif meaningful == effective_required:
            starting_depth = "thin"

        else:
            starting_depth = "deep"

        return {
            "required": required_players,
            "starters": starters,
            "direct_shortage": direct_shortage,
            "direct_surplus": direct_surplus,
            "meaningful_players": meaningful,
            "flex_available": flex_available,
            "starting_depth": starting_depth
        }

    if position == "TE":

        if direct_shortage > 0:

            starting_depth = "short"

        elif meaningful <= required_players + flex_available:

            starting_depth = "thin"

        else:

            starting_depth = "adequate"

        return {
            "required": required_players,
            "starters": starters,
            "direct_shortage": direct_shortage,
            "direct_surplus": direct_surplus,
            "meaningful_players": meaningful,
            "flex_available": flex_available,
            "starting_depth": starting_depth
        }

    if direct_shortage > 0:

        if flex_available > 0:
            starting_depth = "covered_by_flex"
        else:
            starting_depth = "short"

    elif (
        meaningful >= required_players + 2
        or flex_available > 0
    ):

        starting_depth = "deep"

    elif meaningful > required_players:

        starting_depth = "adequate"

    else:

        starting_depth = "thin"

    return {
        "required": required_players,
        "starters": starters,
        "direct_shortage": direct_shortage,
        "direct_surplus": direct_surplus,
        "meaningful_players": meaningful,
        "flex_available": flex_available,
        "starting_depth": starting_depth
    }
def calculate_lineup_strength(
    team,
    roster_configuration,
    ):

    strength = {}
    configured_slots = expand_roster_slots(roster_configuration)
    direct_requirements = {
        position: 0 for position in ("QB", "RB", "WR", "TE")
    }
    flex_slot_codes_by_position = {
        position: [] for position in ("QB", "RB", "WR", "TE")
    }

    for slot in configured_slots:
        if not slot["supported_by_analyzer"]:
            continue

        if slot["slot_type"] == "direct":
            position = slot["slot_code"]
            if position in direct_requirements:
                direct_requirements[position] += 1
        elif slot["slot_type"] == "flex":
            for position in slot["eligible_positions"]:
                if (
                    position in flex_slot_codes_by_position
                    and slot["slot_code"]
                    not in flex_slot_codes_by_position[position]
                ):
                    flex_slot_codes_by_position[position].append(
                        slot["slot_code"]
                    )

    optimal_lineup = team.get(
        "optimal_lineup",
        {}
    )

    for position in [
        "QB",
        "RB",
        "WR",
        "TE"
    ]:

        depth = team[
            "starting_depth"
        ][position]

        meaningful = depth[
            "meaningful_players"
        ]

        direct_shortage = depth.get("direct_shortage", 0)

        direct_players = optimal_lineup.get(
            position,
            []
        )

        position_players = team[
            "positions"
        ].get(
            position,
            []
        )

        position_ids = {
            player.get("player_id")
            for player in position_players
        }

        direct_player_ids = {
            player.get("player_id")
            for player in direct_players
            if player.get("player_id") is not None
        }
        assigned_flex_player_ids = set()
        for slot_code in flex_slot_codes_by_position[position]:
            for player in optimal_lineup.get(slot_code, []):
                player_id = player.get("player_id")
                if (
                    player_id in position_ids
                    and player_id not in direct_player_ids
                    and player_id not in assigned_flex_player_ids
                ):
                    assigned_flex_player_ids.add(player_id)
        flex_used = len(assigned_flex_player_ids)

        required = direct_requirements[position]

        if direct_shortage > 0:

            if flex_used > 0:
                rating = "covered"
            else:
                rating = "weak"

        elif position == "QB":

            if meaningful >= 2:
                rating = "strong"
            elif meaningful == 1:
                rating = "adequate"
            else:
                rating = "weak"

        elif position == "TE":

            if meaningful >= 2:
                rating = "strong"
            elif meaningful == 1:
                rating = "adequate"
            else:
                rating = "weak"

        else:

            if (
                len(direct_players)
                >= required
                and (
                    meaningful
                    >= required + 2
                )
            ):
                rating = "strong"

            elif (
                len(direct_players)
                >= required
                and meaningful
                > required
            ):
                rating = "adequate"

            elif flex_used > 0:

                rating = "covered"

            else:

                rating = "weak"

        strength[position] = {
            "rating": rating,
            "meaningful_players": meaningful,
            "direct_shortage": direct_shortage,
            "flex_used": flex_used
        }

    return strength
def calculate_roster_surplus(
    team,
    roster_configuration,
    ):
    """Classify meaningful offensive players against unique configured slots.

    Meaningful-player tiers retain their existing definition; the shared
    coverage assignment prevents one player satisfying multiple slots.
    """

    surplus = []

    positions = team.get(
        "positions",
        {}
    )

    optimal_lineup = team.get(
        "optimal_lineup",
        {}
    )

    lineup_ids = set()
    for position_players in optimal_lineup.values():
        for player in position_players:
            lineup_ids.add(player.get("player_id"))

    meaningful_tiers = {"elite", "strong", "useful"}
    tier_score = {
        "elite": 5,
        "strong": 4,
        "useful": 3,
        "fringe": 2,
        "deep_waiver": 1,
        "unknown": 0,
    }
    offensive_positions = {"QB", "RB", "WR", "TE"}
    meaningful_positions = {}
    for position in offensive_positions:
        meaningful_players = [
            (index, player)
            for index, player in enumerate(positions.get(position, []))
            if player.get("fantasy_value_tier") in meaningful_tiers
        ]
        meaningful_players.sort(
            key=lambda indexed_player: (
                indexed_player[1].get("player_id") not in lineup_ids,
                -tier_score.get(
                    indexed_player[1].get("fantasy_value_tier"),
                    0,
                ),
                indexed_player[0],
            )
        )
        meaningful_positions[position] = [
            player for _, player in meaningful_players
        ]

    offensive_slots = [
        slot
        for slot in expand_roster_slots(roster_configuration)
        if slot["slot_type"] in {"direct", "flex"}
        and slot["supported_by_analyzer"]
        and set(slot["eligible_positions"]) & offensive_positions
    ]
    coverage = assign_roster_slot_coverage(
        offensive_slots,
        meaningful_positions,
    )
    needed_player_ids = {
        str(assignment["player_id"])
        for assignment in coverage["assignments"]
        if assignment.get("player_id") is not None
    }

    reported_player_ids = set()
    for position in [
        "QB",
        "RB",
        "WR",
        "TE"
    ]:

        meaningful_players = meaningful_positions[position]

        for player in meaningful_players:

            player_id = player.get(
                "player_id"
            )

            if player_id is not None:
                player_key = str(player_id)
                if player_key in reported_player_ids:
                    continue
                reported_player_ids.add(player_key)

            tier = player.get(
                "fantasy_value_tier"
            )

            in_lineup = (
                player_id
                in lineup_ids
            )

            is_needed_for_slots = (
                player_id is not None
                and str(player_id) in needed_player_ids
            )
            if is_needed_for_slots:
                surplus_type = "needed"
            elif position in {"QB", "TE"}:
                surplus_type = "replaceable"
            else:
                surplus_type = "surplus"

            if (
                player.get(
                    "injury_status"
                ) == "IR"
            ):

                status = "injured"

            elif (
                player.get(
                    "roster_status"
                ) == "starter"
            ):

                status = "starter"

            else:

                status = "bench"

            surplus.append({
                "player_id": player_id,
                "name": player.get(
                    "name"
                ),
                "position": position,
                "fantasy_value_tier": tier,
                "roster_status": status,
                "in_optimal_lineup": in_lineup,
                "surplus_type": surplus_type
            })

    return surplus
def calculate_roster_replacement_cost(
    team,
    roster_configuration
    ):
    """Measure lineup-score loss by removing each offensive roster player.

    Both baseline and removal scores use the configured optimal-lineup
    optimizer; K/DEF remain outside its player-selection scope.
    """
    replacement_cost = []

    positions = team.get(
        "positions",
        {}
    )

    tier_score = {
        "elite": 5,
        "strong": 4,
        "useful": 3,
        "fringe": 2,
        "deep_waiver": 1,
        "unknown": 0
    }

    def player_score(player):
        if player.get("status") == "Inactive":
            return -1

        if player.get("injury_status") == "IR":
            return -1

        return (
            tier_score.get(
                player.get("fantasy_value_tier"),
                0
            ) * 100
            + player.get(
                "importance_score",
                0
            )
        )

    def lineup_score(lineup):
        total = 0

        for players in lineup.values():
            for player in players:
                total += player_score(player)

        return total

    baseline_lineup = calculate_optimal_lineup(
        positions,
        roster_configuration,
    )
    original_score = lineup_score(baseline_lineup)
    baseline_assignments = {}

    for lineup_position, players in baseline_lineup.items():
        for player in players:
            player_id = player.get("player_id")
            if player_id is not None:
                baseline_assignments[player_id] = {
                    "lineup_position": lineup_position,
                    "player": player,
                }

    relevant_players = {}
    for position in ("QB", "RB", "WR", "TE"):
        for player in positions.get(position, []):
            player_id = player.get("player_id")
            if player_id is not None:
                relevant_players.setdefault(player_id, player)

    baseline_ids = set(baseline_assignments)

    for player_id, player in relevant_players.items():
        lineup_data = baseline_assignments.get(player_id, {})
        lineup_position = lineup_data.get("lineup_position")

        modified_positions = {
            position: [
                roster_player
                for roster_player in players
                if roster_player.get(
                    "player_id"
                ) != player_id
            ]
            for position, players in positions.items()
        }

        rebuilt_lineup = calculate_optimal_lineup(
            modified_positions,
            roster_configuration,
        )

        rebuilt_score = lineup_score(
            rebuilt_lineup
        )

        score_difference = (
            original_score
            - rebuilt_score
        )

        rebuilt_ids = {
            p.get("player_id")
            for players in rebuilt_lineup.values()
            for p in players
        }

        replacement_ids = rebuilt_ids - baseline_ids

        replacement_player = None
        replacement_player_id = None
        replacement_tier = None
        replacement_lineup_position = None

        if replacement_ids:

            replacement_candidates = []

            for players in rebuilt_lineup.values():
                for candidate in players:

                    candidate_id = candidate.get(
                        "player_id"
                    )

                    if candidate_id not in replacement_ids:
                        continue

                    candidate_position = (
                        candidate.get("position")
                    )

                    candidate_score = player_score(
                        candidate
                    )

                    # Prefer a same-position replacement
                    # when the removed player occupied a
                    # normal positional slot.
                    if lineup_position in [
                        "QB",
                        "RB",
                        "WR",
                        "TE"
                    ]:
                        position_priority = (
                            0
                            if candidate_position
                            == lineup_position
                            else 1
                        )
                    else:
                        # FLEX can legitimately be filled by
                        # RB, WR, or TE, so don't force a
                        # positional preference here.
                        position_priority = 0

                    replacement_candidates.append({
                        "player": candidate,
                        "score": candidate_score,
                        "position_priority":
                            position_priority
                    })

            if replacement_candidates:

                replacement_candidates.sort(
                    key=lambda x: (
                        x["position_priority"],
                        -x["score"]
                    )
                )

                replacement = (
                    replacement_candidates[0]["player"]
                )

                replacement_player = (
                    replacement.get("name")
                )

                replacement_player_id = (
                    replacement.get("player_id")
                )

                replacement_tier = (
                    replacement.get(
                        "fantasy_value_tier"
                    )
                )

                for slot, slot_players in (
                    rebuilt_lineup.items()
                ):
                    if any(
                        p.get("player_id")
                        == replacement_player_id
                        for p in slot_players
                    ):
                        replacement_lineup_position = (
                            slot
                        )
                        break

        if replacement_player is None and score_difference > 0:
            replacement_cost_level = "very_high"
        elif score_difference >= 200:
            replacement_cost_level = "high"

        elif score_difference >= 100:
            replacement_cost_level = "moderate"

        else:
            replacement_cost_level = "low"

        replacement_cost.append({
            "player_id": player_id,
            "name": player.get("name"),
            "position": player.get(
                "position"
            ),
            "lineup_position":
                lineup_position,
            "replacement_player":
                replacement_player,
            "replacement_player_id":
                replacement_player_id,
            "replacement_lineup_position":
                replacement_lineup_position,
            "replacement_tier":
                replacement_tier,
            "lineup_score_before":
                original_score,
            "lineup_score_after":
                rebuilt_score,
            "score_difference":
                score_difference,
            "replacement_cost":
                replacement_cost_level
        })

    return replacement_cost
def calculate_player_protection(
    team
    ):

    protection = []

    surplus_players = team.get(
        "roster_surplus",
        []
    )

    replacement_costs = {
        player.get("player_id"): player
        for player in team.get(
            "roster_replacement_cost",
            []
        )
    }

    for player in surplus_players:

        player_id = player.get(
            "player_id"
        )

        tier = player.get(
            "fantasy_value_tier"
        )

        in_lineup = player.get(
            "in_optimal_lineup",
            False
        )

        surplus_type = player.get(
            "surplus_type"
        )

        status = player.get(
            "roster_status"
        )

        replacement = replacement_costs.get(
            player_id
        )

        if replacement:

            replacement_level = replacement.get(
                "replacement_cost"
            )

            score_difference = replacement.get(
                "score_difference"
            )

            replacement_player = replacement.get(
                "replacement_player"
            )

        else:

            replacement_level = None

            score_difference = None

            replacement_player = None

        # ------------------------------------------
        # INJURED HIGH-VALUE ASSETS
        # ------------------------------------------

        if status == "injured":

            protection_level = "protect"

            reason = (
                "High-value player currently "
                "unavailable due to injury."
            )

        # ------------------------------------------
        # ELITE PLAYERS
        # ------------------------------------------

        elif tier == "elite":

            protection_level = "protect"

            reason = (
                "Elite fantasy asset."
            )

        # ------------------------------------------
        # VERY HIGH REPLACEMENT COST
        # ------------------------------------------

        elif (
            replacement
            and replacement_level == "very_high"
        ):

            protection_level = "protect"

            reason = (
                "Very difficult to replace "
                "within the current roster."
            )

        # ------------------------------------------
        # HIGH REPLACEMENT COST
        # ------------------------------------------

        elif (
            replacement
            and replacement_level == "high"
        ):

            protection_level = "protect"

            reason = (
                "High lineup replacement cost."
            )

        # ------------------------------------------
        # MODERATE REPLACEMENT COST
        # ------------------------------------------

        elif (
            replacement
            and replacement_level == "moderate"
        ):

            protection_level = "hold"

            if replacement_player:

                if score_difference is not None:

                    reason = (
                        f"Moderate lineup replacement cost. "
                        f"Could be replaced by "
                        f"{replacement_player} "
                        f"with a {score_difference}-point loss."
                    )

                else:

                    reason = (
                        f"Moderate lineup replacement cost. "
                        f"Could be replaced by "
                        f"{replacement_player}."
                    )

        # ------------------------------------------
        # LOW REPLACEMENT COST
        # ------------------------------------------

        elif (
            replacement
            and replacement_level == "low"
        ):

            if surplus_type == "surplus":

                protection_level = "tradeable"

                if replacement_player:

                    reason = (
                        f"Low lineup replacement cost. "
                        f"{replacement_player} can replace "
                        f"this player with minimal "
                        f"lineup impact."
                    )

                else:

                    reason = (
                        "Low lineup replacement cost "
                        "and roster surplus."
                    )

            elif in_lineup:

                protection_level = "tradeable"

                reason = (
                    "Currently in the optimal lineup, "
                    "but inexpensive to replace."
                )

            else:

                protection_level = "replaceable"

                reason = (
                    "Low lineup replacement cost "
                    "and limited lineup importance."
                )

        # ------------------------------------------
        # USEFUL SURPLUS
        # ------------------------------------------

        elif (
            surplus_type == "surplus"
            and tier == "strong"
        ):

            protection_level = "tradeable"

            reason = (
                "Strong player who is surplus to "
                "the current optimal lineup."
            )

        elif (
            tier == "useful"
            and surplus_type == "surplus"
        ):

            protection_level = "replaceable"

            reason = (
                "Useful player who is not "
                "needed for the optimal lineup."
            )
        # ------------------------------------------
        # USEFUL DEPTH
        # ------------------------------------------

        elif tier == "useful":

            protection_level = "hold"

            reason = (
                "Useful depth player."
            )

        # ------------------------------------------
        # LOWER-VALUE PLAYERS
        # ------------------------------------------

        else:

            protection_level = "replaceable"

            reason = (
                "Lower-value player with "
                "limited lineup importance."
            )

        protection.append({
            "player_id": player_id,
            "name": player.get(
                "name"
            ),
            "position": player.get(
                "position"
            ),
            "fantasy_value_tier": tier,
            "replacement_cost": replacement_level,
            "replacement_player": replacement_player,
            "score_difference": score_difference,
            "protection": protection_level,
            "reason": reason
        })

    return protection

    protection = []

    surplus_players = team.get(
        "roster_surplus",
        []
    )

    for player in surplus_players:

        tier = player.get(
            "fantasy_value_tier"
        )

        in_lineup = player.get(
            "in_optimal_lineup",
            False
        )

        surplus_type = player.get(
            "surplus_type"
        )

        status = player.get(
            "roster_status"
        )

        if status == "injured":

            protection_level = "protect"

            reason = (
                "High-value player currently "
                "unavailable due to injury."
            )

        elif tier == "elite":

            protection_level = "protect"

            reason = (
                "Elite fantasy asset."
            )

        elif (
            tier == "strong"
            and in_lineup
        ):

            protection_level = "protect"

            reason = (
                "Strong player currently "
                "part of the optimal lineup."
            )

        elif (
            tier == "strong"
            and surplus_type == "surplus"
        ):

            protection_level = "tradeable"

            reason = (
                "Strong player with roster "
                "surplus at the position."
            )

        elif (
            tier == "useful"
            and surplus_type == "surplus"
        ):

            protection_level = "replaceable"

            reason = (
                "Useful player who is not "
                "needed for the optimal lineup."
            )

        elif tier == "useful":

            protection_level = "hold"

            reason = (
                "Useful depth player."
            )

        else:

            protection_level = "replaceable"

            reason = (
                "Lower-value player with "
                "limited lineup importance."
            )

        protection.append({
            "player_id": player.get(
                "player_id"
            ),
            "name": player.get(
                "name"
            ),
            "position": player.get(
                "position"
            ),
            "fantasy_value_tier": tier,
            "protection": protection_level,
            "reason": reason
        }
    )

    return protection
def classify_league_scarcity(
    league_position_analysis
    ):
    scarcity = {}

    for position, data in (
        league_position_analysis.items()
    ):

        median_depth = data[
            "median_depth_score"
        ]

        average_depth = data[
            "average_depth_score"
        ]

        meaningful = data[
            "average_meaningful_players"
        ]

        if (
            median_depth <= 8
            or meaningful <= 1.5
        ):
            level = "high"

        elif (
            median_depth <= 14
            or meaningful <= 2.5
        ):
            level = "moderate"

        else:
            level = "low"

        scarcity[position] = {
            "scarcity": level,
            "median_depth_score":
                median_depth,
            "average_depth_score":
                average_depth,
            "average_meaningful_players":
                meaningful
        }

    return scarcity

def parse_roster_configuration(roster_positions):
    """Normalize raw Sleeper slots into direct, FLEX, bench, and unknown counts.

    FLEX eligibility is recorded here; downstream code interprets the
    normalized data through the shared slot helpers.
    """
    direct_position_codes = {
        "QB", "RB", "WR", "TE", "K", "DEF", "DL", "LB", "DB"
    }

    flex_eligibility = {
        "FLEX": ["RB", "WR", "TE"],
        "WRRB_FLEX": ["RB", "WR"],
        "REC_FLEX": ["WR", "TE"],
        "SUPER_FLEX": ["QB", "RB", "WR", "TE"],
        "IDP_FLEX": ["DL", "LB", "DB"],
    }

    direct_slots = {}
    flex_slots = {}
    nonstarter_slots = {}
    unrecognized_slots = {}

    for raw_slot in roster_positions or []:
        slot_code = str(raw_slot).strip()
        normalized_code = slot_code.upper()

        if normalized_code == "BN":
            nonstarter_slots["BN"] = (
                nonstarter_slots.get("BN", 0) + 1
            )
        elif normalized_code in flex_eligibility:
            slot = flex_slots.setdefault(
                normalized_code,
                {
                    "count": 0,
                    "eligible_positions": flex_eligibility[
                        normalized_code
                    ],
                },
            )
            slot["count"] += 1
        elif normalized_code in direct_position_codes:
            direct_slots[normalized_code] = (
                direct_slots.get(normalized_code, 0) + 1
            )
        else:
            unrecognized_slots[slot_code] = (
                unrecognized_slots.get(slot_code, 0) + 1
            )

    return {
        "direct_slots": dict(sorted(direct_slots.items())),
        "flex_slots": dict(sorted(flex_slots.items())),
        "nonstarter_slots": dict(sorted(nonstarter_slots.items())),
        "unrecognized_slots": dict(sorted(unrecognized_slots.items())),
    }


def get_slot_eligible_positions(slot_code, roster_configuration):
    """Return positions eligible for a slot from normalized configuration."""
    normalized_code = str(slot_code).strip().upper()
    configuration = roster_configuration or {}

    if normalized_code in configuration.get("direct_slots", {}):
        return [normalized_code]

    flex_slot = configuration.get("flex_slots", {}).get(normalized_code)
    if flex_slot is not None:
        return list(flex_slot.get("eligible_positions", []))

    return []


def expand_roster_slots(roster_configuration):
    """Expand normalized counts into ordered, annotated slot instances.

    Bench slots are non-starters; unknown and analyzer-unsupported slots are
    retained with metadata instead of being treated as supported positions.
    """
    configuration = roster_configuration or {}
    direct_slots = configuration.get("direct_slots", {})
    flex_slots = configuration.get("flex_slots", {})
    nonstarter_slots = configuration.get("nonstarter_slots", {})
    unrecognized_slots = configuration.get("unrecognized_slots", {})

    analyzer_supported_positions = {
        "QB", "RB", "WR", "TE", "K", "DEF"
    }
    ordered_codes = [
        code for code in ["QB", "RB", "WR", "TE"]
        if code in direct_slots
    ]
    ordered_codes.extend(
        sorted(code for code in flex_slots if code == "FLEX")
    )
    ordered_codes.extend(
        sorted(code for code in flex_slots if code != "FLEX")
    )
    ordered_codes.extend(
        code for code in ["K", "DEF", "DL", "LB", "DB"]
        if code in direct_slots
    )

    slots = []

    def add_instances(slot_code, count, slot_type, recognized):
        try:
            count = max(0, int(count))
        except (TypeError, ValueError):
            count = 0

        eligible_positions = get_slot_eligible_positions(
            slot_code,
            configuration,
        )
        supported = bool(
            set(eligible_positions) & analyzer_supported_positions
        )

        for ordinal in range(1, count + 1):
            slots.append({
                "slot_code": slot_code,
                "ordinal": ordinal,
                "eligible_positions": eligible_positions.copy(),
                "slot_type": slot_type,
                "is_direct": slot_type == "direct",
                "is_flex": slot_type == "flex",
                "recognized": recognized,
                "supported_by_analyzer": supported,
            })

    for slot_code in ordered_codes:
        if slot_code in direct_slots:
            add_instances(
                slot_code,
                direct_slots[slot_code],
                "direct",
                True,
            )
        else:
            flex_slot = flex_slots[slot_code]
            add_instances(
                slot_code,
                flex_slot.get("count", 0),
                "flex",
                True,
            )

    for slot_code in sorted(nonstarter_slots):
        add_instances(slot_code, nonstarter_slots[slot_code], "nonstarter", True)

    for slot_code in sorted(unrecognized_slots):
        add_instances(
            slot_code,
            unrecognized_slots[slot_code],
            "unknown",
            False,
        )

    return slots


def assign_roster_slot_coverage(slot_instances, positions):
    """Assign unique players to the maximum number of supported slots.

    FLEX coverage retains its existing meaningful/available-player filter;
    K/DEF direct slots are supported here, while IDP slots are not.
    """
    supported_positions = {"QB", "RB", "WR", "TE", "K", "DEF"}
    meaningful_tiers = {"elite", "strong", "useful"}
    supported_slots = []
    unsupported_slots = {}
    candidates_by_slot = []
    eligible_player_ids_by_flex = {}
    all_flex_eligible_player_ids = set()

    for slot in slot_instances:
        if slot["slot_type"] == "nonstarter":
            continue

        if (
            slot["slot_type"] == "unknown"
            or not slot["supported_by_analyzer"]
        ):
            slot_code = slot["slot_code"]
            unsupported_slots[slot_code] = (
                unsupported_slots.get(slot_code, 0) + 1
            )
            continue

        if slot["slot_type"] not in {"direct", "flex"}:
            continue

        eligible_positions = [
            position
            for position in slot["eligible_positions"]
            if position in supported_positions
        ]
        slot_candidates = []
        seen_ids = set()

        for position in eligible_positions:
            for index, player in enumerate(positions.get(position, [])):
                player_id = player.get("player_id")
                candidate_id = (
                    ("player", str(player_id))
                    if player_id is not None
                    else ("missing_id", position, index)
                )

                if candidate_id in seen_ids:
                    continue

                if slot["is_flex"] and (
                    player.get("status") == "Inactive"
                    or player.get("injury_status") == "IR"
                    or player.get("fantasy_value_tier") not in meaningful_tiers
                ):
                    continue

                seen_ids.add(candidate_id)
                slot_candidates.append({
                    "candidate_id": candidate_id,
                    "player_id": player_id,
                    "position": position,
                })

        if slot["is_flex"]:
            eligible_player_ids_by_flex.setdefault(slot["slot_code"], set())
            candidate_ids = {
                candidate["candidate_id"] for candidate in slot_candidates
            }
            eligible_player_ids_by_flex[slot["slot_code"]].update(candidate_ids)
            all_flex_eligible_player_ids.update(candidate_ids)

        supported_slots.append(slot)
        candidates_by_slot.append(slot_candidates)

    best_assignment = None
    best_covered_count = -1

    def search(slot_index, used_candidate_ids, assignment, covered_count):
        nonlocal best_assignment, best_covered_count

        if slot_index == len(supported_slots):
            if covered_count > best_covered_count:
                best_covered_count = covered_count
                best_assignment = assignment.copy()
            return

        if covered_count + len(supported_slots) - slot_index <= best_covered_count:
            return

        for candidate in candidates_by_slot[slot_index]:
            candidate_id = candidate["candidate_id"]
            if candidate_id in used_candidate_ids:
                continue

            used_candidate_ids.add(candidate_id)
            assignment.append(candidate)
            search(
                slot_index + 1,
                used_candidate_ids,
                assignment,
                covered_count + 1,
            )
            assignment.pop()
            used_candidate_ids.remove(candidate_id)

        assignment.append(None)
        search(slot_index + 1, used_candidate_ids, assignment, covered_count)
        assignment.pop()

    search(0, set(), [], 0)

    assignments = []
    for slot, candidate in zip(supported_slots, best_assignment or []):
        if candidate is not None:
            assignments.append({
                "slot_code": slot["slot_code"],
                "ordinal": slot["ordinal"],
                "slot_type": slot["slot_type"],
                "player_id": candidate["player_id"],
                "position": candidate["position"],
            })

    return {
        "assignments": assignments,
        "supported_slot_count": len(supported_slots),
        "covered_slot_count": len(assignments),
        "unsupported_slots": dict(sorted(unsupported_slots.items())),
        "eligible_player_counts_by_flex": {
            slot_code: len(player_ids)
            for slot_code, player_ids in sorted(
                eligible_player_ids_by_flex.items()
            )
        },
        "eligible_player_count_across_flex": len(
            all_flex_eligible_player_ids
        ),
    }


def build_fantasy_analysis(roster_data, roster_configuration):
    """Build team analysis using one normalized league roster configuration."""
    configured_slots = expand_roster_slots(roster_configuration)
    direct_positions = ["QB", "RB", "WR", "TE", "K", "DEF"]
    lineup_requirements = {
        position: sum(
            1
            for slot in configured_slots
            if slot["slot_type"] == "direct"
            and slot["slot_code"] == position
        )
        for position in direct_positions
    }
    for slot in configured_slots:
        if slot["slot_type"] == "direct" and slot["slot_code"] not in lineup_requirements:
            lineup_requirements[slot["slot_code"]] = (
                lineup_requirements.get(slot["slot_code"], 0) + 1
            )

    flex_slots_by_code = {}
    for slot in configured_slots:
        if slot["is_flex"]:
            flex_slots_by_code.setdefault(slot["slot_code"], {
                "count": 0,
                "eligible_positions": slot["eligible_positions"].copy(),
            })
            flex_slots_by_code[slot["slot_code"]]["count"] += 1

    lineup_requirements["FLEX"] = sum(
        flex_slot["count"] for flex_slot in flex_slots_by_code.values()
    )
    flex_positions = sorted({
        position
        for flex_slot in flex_slots_by_code.values()
        for position in flex_slot["eligible_positions"]
    })

    analysis = {
        "roster_configuration": roster_configuration,
        "lineup_requirements": lineup_requirements,
        "flex_positions": sorted(flex_positions),
        "flex_slot_requirements": flex_slots_by_code,
        "teams": {}
    }

    for roster_id, roster in roster_data.items():

        positions = {
            "QB": [],
            "RB": [],
            "WR": [],
            "TE": [],
            "K": [],
            "DEF": []
        }

        position_summary = {}

        starter_ids = {
            str(player["player_id"])
            for player in roster.get("starters", [])
        }

        reserve_ids = {
            str(player["player_id"])
            for player in roster.get("reserve", [])
        }

        taxi_ids = {
            str(player["player_id"])
            for player in roster.get("taxi", [])
        }

        for player in roster.get("players", []):

            player_id = str(
                player.get("player_id")
            )

            position = player.get("position")

            if position not in positions:
                continue

            if player_id in starter_ids:
                roster_status = "starter"

            elif player_id in reserve_ids:
                roster_status = "reserve"

            elif player_id in taxi_ids:
                roster_status = "taxi"

            else:
                roster_status = "bench"

            value_tier = fantasy_value_tier(player)

            positions[position].append({
                "player_id": player_id,
                "name": clean_name(player.get("name")),
                "team": player.get("team"),
                "status": player.get("status"),
                "injury_status": player.get("injury_status"),
                "roster_status": roster_status,
                "fantasy_value_tier": value_tier,
                "importance_score": fantasy_importance_score({
                    "fantasy_value_tier": value_tier,
                    "roster_status": roster_status
                })
            })

        for position, players_at_position in positions.items():

            starters = [
                player
                for player in players_at_position
                if player["roster_status"] == "starter"
            ]

            bench = [
                player
                for player in players_at_position
                if player["roster_status"] == "bench"
            ]

            reserve = [
                player
                for player in players_at_position
                if player["roster_status"] == "reserve"
            ]

            taxi = [
                player
                for player in players_at_position
                if player["roster_status"] == "taxi"
            ]

            importance_scores = [
                player["importance_score"]
                for player in players_at_position
            ]

            position_summary[position] = {
                "total": len(players_at_position),
                "starters": len(starters),
                "bench": len(bench),
                "reserve": len(reserve),
                "taxi": len(taxi),
                "depth_score": sum(importance_scores),
                "meaningful_players": sum(
                    1
                    for player in players_at_position
                    if player["fantasy_value_tier"] in [
                        "elite",
                        "strong",
                        "useful"
                    ]
                )
            }
            
                    
        # ------------------------------------------
        # LINEUP COVERAGE
        # ------------------------------------------

        coverage_result = assign_roster_slot_coverage(
            configured_slots,
            positions,
        )
        assignments = coverage_result["assignments"]
        lineup_coverage = {}

        for position in direct_positions:
            total_players = len(positions[position])
            required = lineup_requirements[position]
            direct_coverage = sum(
                1
                for assignment in assignments
                if assignment["slot_type"] == "direct"
                and assignment["slot_code"] == position
            )

            lineup_coverage[position] = {
                "required": required,
                "total": total_players,
                "direct_coverage": direct_coverage,
                "surplus": max(total_players - required, 0),
                "shortage": max(required - direct_coverage, 0),
            }

        flex_coverage_by_code = {}
        for slot_code, flex_slot in flex_slots_by_code.items():
            supported_required = sum(
                1
                for slot in configured_slots
                if slot["slot_type"] == "flex"
                and slot["slot_code"] == slot_code
                and slot["supported_by_analyzer"]
            )
            flex_coverage = sum(
                1
                for assignment in assignments
                if assignment["slot_type"] == "flex"
                and assignment["slot_code"] == slot_code
            )
            flex_coverage_by_code[slot_code] = {
                "required": flex_slot["count"],
                "supported_required": supported_required,
                "eligible_players": coverage_result[
                    "eligible_player_counts_by_flex"
                ].get(slot_code, 0),
                "coverage": flex_coverage,
                "shortage": max(supported_required - flex_coverage, 0),
                "unsupported": flex_slot["count"] - supported_required,
            }

        supported_flex_required = sum(
            data["supported_required"]
            for data in flex_coverage_by_code.values()
        )
        flex_coverage = sum(
            data["coverage"] for data in flex_coverage_by_code.values()
        )
        lineup_coverage["FLEX"] = {
            "required": lineup_requirements["FLEX"],
            "supported_required": supported_flex_required,
            "eligible_players": coverage_result[
                "eligible_player_count_across_flex"
            ],
            "coverage": flex_coverage,
            "shortage": max(supported_flex_required - flex_coverage, 0),
            "unsupported": lineup_requirements["FLEX"] - supported_flex_required,
        }
        lineup_coverage["flex_slots"] = flex_coverage_by_code
        lineup_coverage["summary"] = {
            "supported_configured_slots": coverage_result[
                "supported_slot_count"
            ],
            "covered_slots": coverage_result["covered_slot_count"],
            "uncovered_slots": (
                coverage_result["supported_slot_count"]
                - coverage_result["covered_slot_count"]
            ),
            "unsupported_slots": coverage_result["unsupported_slots"],
            "assignments": assignments,
        }
            
        analysis["teams"][str(roster_id)] = {
            "team_name": clean_name(
                roster.get("team_name")
            ),
            "owner": clean_name(
                roster.get("owner")
            ),
            "positions": positions,
            "position_summary": position_summary,
            "lineup_coverage": lineup_coverage,
            "position_need": {}
        }
    analysis["league_position_analysis"] = (
        build_league_position_analysis(
            analysis
        )
    )
    analysis["league_position_scarcity"] = classify_league_scarcity(
        {
            position: data
            for position, data in analysis[
                "league_position_analysis"
            ].items()
            if position in [
                "QB",
                "RB",
                "WR",
                "TE",
            ]
        }
    )
    

    for roster_id, team in analysis["teams"].items():
        
        optimal_lineup = calculate_optimal_lineup(
            team["positions"],
            roster_configuration
        )

        team["optimal_lineup"] = optimal_lineup
        
        team["position_need"] = {}

        for position in [
            "QB",
            "RB",
            "WR",
            "TE",
        ]:

            team_summary = team[
                "position_summary"
            ][position]

            team["position_need"][position] = (
                classify_position_need(
                    position,
                    team_summary,
                    analysis[
                        "league_position_analysis"
                    ],
                    configured_slots,
                )
            )
        team["starting_depth"] = {}

        for position in [
            "QB",
            "RB",
            "WR",
            "TE"
        ]:

            team_summary = team[
                "position_summary"
            ][position]

            team["starting_depth"][position] = (
                classify_starting_depth(
                    position,
                    team_summary,
                    team["positions"],
                    optimal_lineup,
                    configured_slots,
                )
            )
            
        team["lineup_strength"] = calculate_lineup_strength(
            team,
            roster_configuration,
        )
        team["roster_surplus"] = calculate_roster_surplus(
            team,
            roster_configuration,
        )
        team["roster_replacement_cost"] = (
            calculate_roster_replacement_cost(
            team,
            roster_configuration
            )
        )       
        team["player_protection"] = (
            calculate_player_protection(
                team
            )
        )        
    return analysis

def fantasy_value_tier(player):
    """
    Convert Sleeper search_rank into a simple fantasy
    depth tier.

    Lower search_rank = more highly ranked player.
    """

    rank = player.get("search_rank")

    if rank is None:
        return "unknown"

    try:
        rank = int(rank)
    except Exception:
        return "unknown"

    if rank <= 50:
        return "elite"

    if rank <= 120:
        return "strong"

    if rank <= 250:
        return "useful"

    if rank <= 400:
        return "fringe"

    return "deep_waiver"
def fantasy_importance_score(player):
    tier_scores = {
        "elite": 5,
        "strong": 4,
        "useful": 3,
        "fringe": 2,
        "deep_waiver": 1,
        "unknown": 0
    }

    status_scores = {
        "starter": 2,
        "bench": 1,
        "reserve": 0,
        "taxi": 0
    }

    tier = player.get("fantasy_value_tier", "unknown")
    status = player.get("roster_status", "bench")

    return (
        tier_scores.get(tier, 0)
        + status_scores.get(status, 0)
    )
def waiver_value_score(
    player,
    position_need,
    league_scarcity
    ):
    score = 0

    rank = player.get("search_rank")

    if rank is not None:
        try:
            rank = int(rank)

            if rank <= 50:
                score += 50
            elif rank <= 100:
                score += 40
            elif rank <= 150:
                score += 30
            elif rank <= 250:
                score += 20
            elif rank <= 400:
                score += 10

        except Exception:
            pass

    need_scores = {
        "high": 30,
        "moderate": 15,
        "low": 0,
        "unknown": 0
    }

    scarcity_scores = {
        "high": 20,
        "moderate": 10,
        "low": 0,
        "unknown": 0
    }

    score += need_scores.get(
        position_need,
        0
    )

    score += scarcity_scores.get(
        league_scarcity,
        0
    )

    return score
def build_waiver_analysis(
    waiver_pool,
    fantasy_analysis
    ):
    """Rank offensive waiver candidates using configuration-aware need/scarcity.

    The established waiver model intentionally covers QB/RB/WR/TE only.
    """
    my_team = fantasy_analysis[
        "teams"
    ].get(
        str(MY_ROSTER_ID)
    )

    if not my_team:
        return {
            "available": False,
            "candidates": []
        }

    league_scarcity = fantasy_analysis.get(
        "league_position_scarcity",
        {}
    )

    candidates = []

    for player in waiver_pool:

        position = player.get(
            "position"
        )

        if position not in {
            "QB",
            "RB",
            "WR",
            "TE",
        }:
            continue

        position_need = my_team[
            "position_need"
        ].get(
            position,
            {}
        )

        need_level = position_need.get(
            "need",
            "unknown"
        )

        scarcity = league_scarcity.get(
            position,
            {}
        ).get(
            "scarcity",
            "unknown"
        )

        score = waiver_value_score(
            player,
            need_level,
            scarcity
        )

        candidates.append({
            "player_id": player[
                "player_id"
            ],
            "name": player[
                "name"
            ],
            "position": position,
            "team": player.get(
                "team"
            ),
            "status": player.get(
                "status"
            ),
            "injury_status": player.get(
                "injury_status"
            ),
            "search_rank": player.get(
                "search_rank"
            ),
            "team_need": need_level,
            "league_scarcity": scarcity,
            "waiver_value_score": score
        })

    candidates.sort(
        key=lambda player: (
            -player[
                "waiver_value_score"
            ],
            player[
                "search_rank"
            ]
                if player[
                    "search_rank"
                ] is not None
                else 999999
        )
    )

    return {
        "available": True,
        "team": my_team[
            "team_name"
        ],
        "candidates": candidates
    }
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
        "search_rank": p.get("search_rank"),
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

def reconstruct_trade(tx, roster_data, players, week=None):
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
        "week": week,
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

def build_transaction_record(
    tx,
    roster_data,
    players,
    week
    ):
    tx_type = tx.get("type")

    if tx_type == "trade":
        return {
            "week": week,
            "type": "trade",
            "status": tx.get("status"),
            "created": tx.get("created"),
            "transaction_id": tx.get("transaction_id"),
            "trade": reconstruct_trade(
                tx,
                roster_data,
                players,
                week
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
        "week": week,
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
            rostered_ids.add(
                str(player["player_id"])
            )

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
                x
                for x in [
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

    pool.sort(
        key=rank_key
    )

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
            "team_name": clean_name(roster["team_name"]),
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
                    players,
                    tx.get("week")
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
            "week": trade.get("week"),
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

        status = str(
            tx.get("status") or ""
        ).lower()

        activity.append({
            "type": "waiver",
            "week": tx.get("week"),
            "transaction_id": tx.get(
                "transaction_id"
            ),
            "created": tx.get("created"),
            "status": status,
            "details": tx,
        })

    # --------------------------------------------------------
    # FREE AGENT ADDS
    # --------------------------------------------------------

    for tx in classified["adds"]:
        activity.append({
            "type": "add",
            "week": tx.get("week"),
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
            "week": tx.get("week"),
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
            "week": tx.get("week"),
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

            # Show Sleeper's actual waiver result
            if tx_type == "waiver":
                status = str(
                    tx.get("status") or ""
                ).upper()

                if status:
                    tx_label = f"waiver {status}"
                else:
                    tx_label = "waiver"
            else:
                tx_label = tx_type

            lines.append(
                f"- Week {week} | "
                f"**{md(team_name)}** | "
                f"{tx_label} | "
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
            
            week = item.get("week")

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

                status = str(
                    item.get("status") or ""
                ).lower()

                details = item.get(
                    "details",
                    {}
                )

                adds = details.get(
                    "adds",
                    []
                )

                drops = details.get(
                    "drops",
                    []
                )

                if status == "complete":
                    lines.append(
                        "#### WAIVER CLAIM — COMPLETE"
                    )

                elif status == "failed":
                    lines.append(
                        "#### WAIVER CLAIM — FAILED"
                    )

                else:
                    lines.append(
                        "#### WAIVER CLAIM"
                    )

                lines.append("")

                if adds:
                    for player in adds:

                        team_name = player.get(
                            "team_name",
                            f"Roster {player.get('roster_id', 'Unknown')}"
                        )

                        player_name = player.get(
                            "name",
                            player.get(
                                "player_id",
                                "Unknown Player"
                            )
                        )

                        lines.append(
                            f"- **{md(team_name)}** "
                            f"requested **{md(player_name)}**"
                        )

                if drops:
                    for player in drops:

                        team_name = player.get(
                            "team_name",
                            f"Roster {player.get('roster_id', 'Unknown')}"
                        )

                        player_name = player.get(
                            "name",
                            player.get(
                                "player_id",
                                "Unknown Player"
                            )
                        )

                        lines.append(
                            f"- **{md(team_name)}** "
                            f"dropped **{md(player_name)}**"
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

            if week is not None:
                lines.append(
                f"Week: `{week}`"
            )

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
    print("SLEEPER V3.2 SNAPSHOT")
    print("==========================================")
    print("")
    print("Pulling league data...")

    # --------------------------------------------------------
    # Core league data
    # --------------------------------------------------------

    league = api_get(
        f"/league/{LEAGUE_ID}"
    )

    roster_configuration = parse_roster_configuration(
        league.get("roster_positions")
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

    print("Loading player database...")

    players = get_players_cached()

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
                    players,
                    week
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
        "snapshot_version": "3.2",

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
    
    snapshot["fantasy_analysis"] = build_fantasy_analysis(
        roster_data,
        roster_configuration
    )
    snapshot["waiver_analysis"] = build_waiver_analysis(
        waiver_pool,
        snapshot["fantasy_analysis"]
    )

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
