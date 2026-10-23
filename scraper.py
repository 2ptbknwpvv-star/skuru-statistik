import asyncio
from playwright.async_api import async_playwright
import json
import re
from datetime import datetime

TARGET_TEAMS = ["Skuru IK 4", "Skuru IK 2", "Skuru IK 1"]

# Rätta, fullständiga adresser som pekar direkt på spelschemat
FIXED_URLS = [
    {"namn": "Skuru IK 4", "url": "https://profixio.com"},
    {"namn": "Skuru IK 2", "url": "https://profixio.com"},
    {"namn": "Skuru IK 1", "url": "https://profixio.com"}
]

async def scrape_to_html_direct():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale="sv-SE", timezone_id="Europe/Stockholm")
        page = await context.new_page()
        
        stats_master = {team: {} for team in TARGET_TEAMS}

        print("--- Steg 1: Läser spelscheman ---")
        for team in FIXED_URLS:
            try:
                await page.goto(team["url"])
                await page.wait_for_timeout(6000)
                
                # Hämtar ut absolut all text som finns på sidan (förbi iFrames och dolda block)
                page_text = await page.evaluate("() => document.body.innerText")
                lines = page_text.split("\n")
                
                for line in lines:
                    line = line.strip()
                    if not line or len(line) < 5:
                        continue
                        
                    # Letar efter mönstret: [Spelarnamn] + [Mål] i slutet av raden
                    player_match = re.search(r'(?:\d+\s+)?([A-ZÅÄÖa-zåäö][-A-ZÅÄÖa-zåäö\s]+?)\s+(\d+)\s*$', line)
                    if player_match:
                        name = player_match.group(1).strip()
                        goals = int(player_match.group(2))
                        
                        if name in ["Matchinfo", "Resultat", "Domare", "Ledare", "Spelare", "Mål", "Lag", "Slutresultat", "Hemma", "Borta"] or len(name) < 4:
                            continue
                            
                        if name not in stats_master[team['namn']]:
                            stats_master[team['namn']][name] = {"Spelarnamn": name, "Matcher": 0, "Mål": 0, "Utvisningar": 0}
                        
                        stats_master[team['namn']][name]["Matcher"] += 1
                        stats_master[team['namn']][name]["Mål"] += goals

                    # Sök efter 2-minutersutvisningar
                    if "2'" in line or "2-min" in line:
                        for r_name in stats_master[team['namn']]:
                            if r_name.lower() in line.lower():
                                stats_master[team['namn']][r_name]["Utvisningar"] += 1
                                
            except Exception as e:
                print(f"Fel vid insamling av {team['namn']}: {e}")

        await browser.close()

        # Steg 2: Sortera spelarna efter flest gjorda mål
        final_data = {}
        for t_name in TARGET_TEAMS:
            final_data[t_name] = sorted(list(stats_master[t_name].values()), key=lambda x: x["Mål"], reverse=True)

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open("index.html", "r", encoding="utf-8") as f:
            html_content = f.read()

        html_content = re.sub(r'const statsData = \{.*?\};', f'const statsData = {json.dumps(final_data, ensure_ascii=False)};', html_content, flags=re.DOTALL)
        html_content = re.sub(r'const lastUpdated = ".*?";', f'const lastUpdated = "{now_str}";', html_content)

        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        print("index.html har uppdaterats framgångsrikt!")

if __name__ == "__main__":
    asyncio.run(scrape_to_html_direct())
