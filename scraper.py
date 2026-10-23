import asyncio
from playwright.async_api import async_playwright
import json
import re
from datetime import datetime

TARGET_TEAMS = ["Skuru IK 4", "Skuru IK 2", "Skuru IK 1"]

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

        print("--- Steg 1: Öppnar spelscheman ---")
        for team in FIXED_URLS:
            try:
                print(f"Öppnar spelschema för {team['namn']}...")
                await page.goto(team["url"])
                await page.wait_for_timeout(6000)
                
                # Hitta alla länkar till matcherna
                match_links = await page.locator("a[href*='/match/'], a[href*='matchid'], a:has-text('Matchinfo'), a:has-text('Live')").all()
                
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

                        # Ny bombsäker cellskrapning: Vi letar efter ALLA tabellrader inuti matchen
                        rows = await popup.locator("table tr").all()
                        for row in rows:
                            cells = await row.locator("td").all_text_contents()
                            if len(cells) < 2:
                                continue
                            
                            # Rensa cellerna från tomrum
                            cells = [c.strip() for c in cells]
                            
                            # Hitta vilken cell som innehåller namnet (ofta cell index 1 eller 2)
                            name = ""
                            goals = 0
                            penalties = 0
                            
                            for c in cells:
                                # Om cellen innehåller bokstäver och är längre än 5 tecken, är det namnet
                                if re.match(r'^[A-ZÅÄÖa-zåäö][-A-ZÅÄÖa-zåäö\s]+$', c) and len(c) > 5:
                                    if c not in ["Matchinfo", "Resultat", "Domare", "Ledare", "Spelare", "Mål", "Lag", "Slutresultat", "Hemma", "Borta"]:
                                        name = c
                                        break
                            
                            if not name:
                                continue
                                
                            # Sök efter mål i radens alla celler (letar efter en ren siffra som inte är tröjnumret)
                            for c in cells:
                                if c.isdigit() and c != cells[0]: # Tröjnumret ligger nästan alltid först
                                    goals = int(c)
                                if "2'" in c or "2-min" in c:
                                    penalties += c.count("2'")

                            if name not in stats_master[team['namn']]:
                                stats_master[team['namn']][name] = {"Spelarnamn": name, "Matcher": 0, "Mål": 0, "Utvisningar": 0}
                            
                            stats_master[team['namn']][name]["Matcher"] += 1
                            stats_master[team['namn']][name]["Mål"] += goals
                            stats_master[team['namn']][name]["Utvisningar"] += penalties
                                        
                        await popup.close()
                    except Exception as match_error:
                        print(f"    Kunde inte läsa enskild match {idx}: {match_error}")
            except Exception as e:
                print(f"  Fel vid skrapning av {team['namn']}: {e}")

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
