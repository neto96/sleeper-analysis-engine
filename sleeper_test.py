import urllib.request
import json

LEAGUE_ID = "1389736505374691328"

url = f"https://api.sleeper.app/v1/league/{LEAGUE_ID}"

with urllib.request.urlopen(url) as response:
    data = json.loads(response.read().decode())

print("League:", data.get("name"))
print("League ID:", data.get("league_id"))
print("Season:", data.get("season"))
print("Status:", data.get("status"))