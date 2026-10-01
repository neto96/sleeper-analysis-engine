import requests
import json

LEAGUE_ID = "1389736505374691328"

BASE_URL = "https://api.sleeper.app/v1"


def get_json(endpoint):
    response = requests.get(
        f"{BASE_URL}{endpoint}",
        timeout=15
    )
    response.raise_for_status()
    return response.json()


print("==========================================")
print("SLEEPER RAW TRANSACTION INSPECTOR")
print("==========================================")

# Get current NFL state
nfl_state = get_json("/state/nfl")

current_week = int(nfl_state.get("week", 1))

print(f"Current NFL week: {current_week}")
print()

# Get users and rosters so we can identify teams
users = get_json(f"/league/{LEAGUE_ID}/users")
rosters = get_json(f"/league/{LEAGUE_ID}/rosters")

users_by_id = {
    user["user_id"]: user
    for user in users
}

rosters_by_id = {
    str(roster["roster_id"]): roster
    for roster in rosters
}


def team_name(roster_id):
    roster = rosters_by_id.get(str(roster_id))

    if not roster:
        return f"Roster {roster_id}"

    user = users_by_id.get(roster.get("owner_id"))

    if user:
        metadata = user.get("metadata") or {}

        return (
            metadata.get("team_name")
            or user.get("display_name")
            or user.get("username")
            or f"Roster {roster_id}"
        )

    return f"Roster {roster_id}"


# Pull the last 3 transaction weeks
weeks = sorted(
    set([
        max(1, current_week - 2),
        max(1, current_week - 1),
        current_week
    ])
)

found_transactions = 0

for week in weeks:

    print()
    print("==========================================")
    print(f"WEEK {week}")
    print("==========================================")

    try:
        transactions = get_json(
            f"/league/{LEAGUE_ID}/transactions/{week}"
        )
    except Exception as error:
        print(f"ERROR: {error}")
        continue

    if not transactions:
        print("No transactions.")
        continue

    for tx in transactions:

        found_transactions += 1

        print()
        print("------------------------------------------")
        print(f"Transaction ID: {tx.get('transaction_id')}")
        print(f"Type:           {tx.get('type')}")
        print(f"Status:         {tx.get('status')}")
        print(f"Created:        {tx.get('created')}")
        print(f"Roster IDs:     {tx.get('roster_ids')}")
        print()

        roster_ids = tx.get("roster_ids") or []

        print("TEAMS INVOLVED:")

        for roster_id in roster_ids:
            print(
                f"  {roster_id}: {team_name(roster_id)}"
            )

        print()
        print("ADDS:")
        print(
            json.dumps(
                tx.get("adds"),
                indent=2
            )
        )

        print()
        print("DROPS:")
        print(
            json.dumps(
                tx.get("drops"),
                indent=2
            )
        )

        print()
        print("DRAFT PICKS:")
        print(
            json.dumps(
                tx.get("draft_picks"),
                indent=2
            )
        )

        print()
        print("WAIVER BUDGET:")
        print(
            json.dumps(
                tx.get("waiver_budget"),
                indent=2
            )
        )

        print()
        print("FULL RAW TRANSACTION:")
        print(
            json.dumps(
                tx,
                indent=2
            )
        )

print()
print("==========================================")
print(f"TOTAL TRANSACTIONS FOUND: {found_transactions}")
print("==========================================")