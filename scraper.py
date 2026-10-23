import asyncio
from playwright.async_api import async_playwright
import json
import re
from datetime import datetime

TARGET_TEAMS = ["Skuru IK 4", "Skuru IK 2", "Skuru IK 1"]

# Fullständiga och direkta spelschemalänkar som tvingar Profixio att visa SPELADE matcher direkt
FIXED_URLS = [
    {"namn": "Skuru IK 4", "url": "https://profixio.com"},
    {"namn": "Skuru IK 2", "url": "https://profixio.com"},
    {"namn": "Skuru IK 1", "url": "https://profixio.com"}
]

async def scrape_to_html_direct():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Tvinga svenskt språk och zon i webbläsar-kontexten
        context = await browser.new_context(locale="sv-SE", timezone_id="Europe/Stockholm")
        page = await context.new_page()
        
        stats_master = {team: {} for team in TARGET_TEAMS}

        print("--- Steg 1: Skrapar matcher från de verifierade länkarna ---")
        for team in FIXED_URLS:
            try:
                print(f"Öppnar spelschema för {team['namn']}...")
                await page.goto(team["url"])
                # Ge sidan ordentligt med tid att ladda in JavaScript-elementen fullt ut
                await page.wait_for_timeout(7000)
                
                # Bred sökning efter alla matchlänkar/ikoner oavsett textinnehåll
                match_links = await page.locator("a[href*='/match/'], a[href*='matchid'], a:has-text('Matchinfo'), a:has-text('Live')").all()
                
                # Sortera bort dubblett-länkar
                seen_hrefs = set()
                valid_buttons = []
                for link in match_links:
                    href = await link.get_attribute("href")
                    if href and href not in seen_hrefs:
                        seen_hrefs.add(href)
                        valid_buttons.append(link)
                
                print(f"  Hittade {len(valid_buttons)} unika matchprotokoll för {team['namn']}.")
                
                for idx in range(len(valid_buttons)):
                    try:
                        async with page.expect_popup() as popup_info:
                            await valid_buttons[idx].click()
                        
                        popup = await popup_info.value
                        await popup.wait_for_load_state("networkidle")
                        await popup.wait_for_timeout(5000)

                        # Hämta ut all synlig text från matchbladet
                        full_page_text = await popup.evaluate("() => document.body.innerText")
                        lines = full_page_text.split("\n")
                        
                        for line in lines:
                            line = line.strip()
                            if not line or len(line) < 4:
                                continue
                            
                            # Matchar mönster som "9 Spelarnamn Spelarkvist 4" eller "Spelarnamn 3" i slutet av en rad
                            player_match = re.search(r'(?:\d+\s+)?([A-ZÅÄÖa-zåäö][-A-ZÅÄÖa-zåäö\s]+?)\s+(\d+)\s*$', line)
                            if player_match:
                                name = player_match.group(1).strip()
                                goals = int(player_match.group(2))
                                
                                # Filtrera bort gränssnittstext
                                if name in ["Matchinfo", "Resultat", "Domare", "Ledare", "Spelare", "Mål", "Lag", "Slutresultat", "Hemma", "Borta", "Period"] or len(name) < 5:
                                    continue
                                
                                if name not in stats_master[team['namn']]:
                                    stats_master[team['namn']][name] = {"Spelarnamn": name, "Matcher": 0, "Mål": 0, "Utvisningar": 0}
                                
                                stats_master[team['namn']][name]["Matcher"] += 1
                                stats_master[team['namn']][name]["Mål"] += goals

                            # Detektera 2-minutersutvisningar
                            if "2'" in line or "2-min" in line:
                                for r_name in stats_master[team['namn']]:
                                    if r_name.lower() in line.lower():
                                        stats_master[team['namn']][r_name]["Utvisningar"] += 1
                                        
                        await popup.close()
                    except Exception as match_error:
                        print(f"    Kunde inte läsa enskild match {idx}: {match_error}")
            except Exception as e:
                print(f"  Allvarligt fel vid skrapning av {team['namn']}: {e}")

        await browser.close()

        print("\n--- Steg 2: Kompilerar datan till HTML ---")
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
        print(f"index.html har uppdaterats framgångsrikt kl. {now_str}!")

if __name__ == "__main__":
    asyncio.run(scrape_to_html_direct())
