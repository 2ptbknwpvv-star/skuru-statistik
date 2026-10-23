import urllib.request
import json
import re
from datetime import datetime

TARGET_TEAMS = ["Skuru IK 4", "Skuru IK 2", "Skuru IK 1"]

# De officiella ID-numren till dina lag i Profixios databas
TEAM_IDS = {
    "Skuru IK 4": "1598917",
    "Skuru IK 2": "1581327",
    "Skuru IK 1": "1581326"
}

def scrape_data():
    stats_master = {team: {} for team in TARGET_TEAMS}
    
    print("--- Hämtar matchdata direkt från Profixio API ---")
    for team_name, team_id in TEAM_IDS.items():
        try:
            # Vi anropar Profixios dolda dataschema för att få ut alla spelade matcher direkt
            api_url = f"https://profixio.com{team_id}/matches?lang=sv"
            
            req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                match_data = json.loads(response.read().decode())
            
            # Gå igenom alla tillgängliga matcher i listan
            for match in match_data.get("matches", []):
                # Vi är bara intresserade av avslutade matcher där det finns registrerade händelser
                if match.get("status") == "FINISHED" or match.get("played", False):
                    match_id = match.get("id")
                    
                    # Hämta det officiella matchprotokollet för denna specifika match
                    protocol_url = f"https://profixio.com{match_id}/protocol"
                    req_p = urllib.request.Request(protocol_url, headers={'User-Agent': 'Mozilla/5.0'})
                    
                    try:
                        with urllib.request.urlopen(req_p) as p_response:
                            protocol = json.loads(p_response.read().decode())
                            
                        # Läs av alla spelare och händelser inifrån matchrapporten
                        for person in protocol.get("persons", []):
                            if person.get("club_name") == "Skuru IK" or team_name in person.get("team_name", ""):
                                name = f"{person.get('first_name', '')} {person.get('last_name', '')}".strip()
                                goals = int(person.get("goals", 0))
                                suspensions = int(person.get("suspensions_2min", 0))
                                
                                if len(name) < 4 or name in ["", "Unknown Player"]:
                                    continue
                                    
                                if name not in stats_master[team_name]:
                                    stats_master[team_name][name] = {"Spelarnamn": name, "Matcher": 0, "Mål": 0, "Utvisningar": 0}
                                
                                stats_master[team_name][name]["Matcher"] += 1
                                stats_master[team_name][name]["Mål"] += goals
                                stats_master[team_name][name]["Utvisningar"] += suspensions
                    except:
                        continue # Hoppa över matchen om protokollet inte är släppt än
                        
        except Exception as e:
            print(f"Kunde inte hämta data för {team_name}: {e}")

    # Sortera alla spelare baserat på flest gjorda mål
    final_data = {}
    for t_name in TARGET_TEAMS:
        final_data[t_name] = sorted(list(stats_master[t_name].values()), key=lambda x: x["Mål"], reverse=True)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Läs in och uppdatera din index.html med den färska levande datan
    with open("index.html", "r", encoding="utf-8") as f:
        html_content = f.read()

    html_content = re.sub(r'const statsData = \{.*?\};', f'const statsData = {json.dumps(final_data, ensure_ascii=False)};', html_content, flags=re.DOTALL)
    html_content = re.sub(r'const lastUpdated = ".*?";', f'const lastUpdated = "{now_str}";', html_content)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print("Klart! Hemsidan har uppdaterats med levande spelardata.")

if __name__ == "__main__":
    scrape_data()
