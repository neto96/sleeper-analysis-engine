import requests

LEAGUE_ID = "1389736505374691328"

BASE_URL = "https://api.sleeper.app/v1"

# Get league information
league_response = requests.get(
    f"{BASE_URL}/league/{LEAGUE_ID}",
    timeout=10
)
league_response.raise_for_status()
league = league_response.json()

# Get league users
users_response = requests.get(
    f"{BASE_URL}/league/{LEAGUE_ID}/users",
    timeout=10
)
users_response.raise_for_status()
users = users_response.json()

print("===================================")
print("Sleeper League Users")
print("===================================")
print(f"League: {league.get('name')}")
print(f"Season: {league.get('season')}")
print()

for user in users:
    display_name = user.get("display_name")
    username = user.get("username")
    user_id = user.get("user_id")

    print(f"Team:     {display_name}")
    print(f"Username: {username}")
    print(f"User ID:  {user_id}")
    print("-----------------------------------")