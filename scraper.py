import asyncio
from playwright.async_api import async_playwright
import json
import re
from datetime import datetime

COMPETITION_URL = "https://profixio.com"
TARGET_TEAMS = ["Skuru IK 4", "Skuru IK 2", "Skuru IK 1"]

async def scrape_to_html_direct():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale="sv-SE", timezone_id="Europe/Stockholm")
        page = await context.new_page()
        
        resolved_teams = []
        stats_master = {}

        print("--- Steg 1: Söker efter laglänkar automatiskt ---")
        try:
            await page.goto(COMPETITION_URL)
            await page.wait_for_timeout(4000)
        except Exception as e:
            print(f"Fel vid laddning: {e}")
            await browser.close()
            return

        for team_name in TARGET_TEAMS:
            stats_master[team_name] = {}
            try:
                team_link_locator = page.locator(f"a:has-text('{team_name}')")
                if await team_link_locator.count() > 0:
                    href = await team_link_locator.first.get_attribute("href")
                    if href:
                        full_url = href if href.startswith("http") else f"https://profixio.com{href}"
                        full_url = full_url.replace("t=schedule", "") + "&t=schedule&f=played"
                        resolved_teams.append({"namn": team_name, "url": full_url})
            except:
                pass

        # Reservlänkar ifall den dynamiska sökningen misslyckas
        if not resolved_teams:
            resolved_teams = [
                {"namn": "Skuru IK 4", "url": "https://profixio.com/teams/1598917?k=1183572&t=schedule&f=played"},
                {"namn": "Skuru IK 2", "url": "https://profixio.com/teams/1581327?k=1183570&t=schedule&f=played"},
                {"namn": "Skuru IK 1", "url": "https://profixio.com/teams/1581326?k=1183570&t=schedule&f=played"}
            ]

        print("--- Steg 2: Skrapar matcher från Profixio ---")
        for team in resolved_teams:
            try:
                await page.goto(team["url"])
                await page.wait_for_timeout(5000)
                match_buttons = await page.locator("a:has-text('Matchinfo'), button:has-text('Matchinfo'), a:has-text('Live'), button:has-text('Live'), a[href*='match']").all()
                print(f"Hittade {len(match_buttons)} matcher för {team['namn']}.")
                
                for idx in range(len(match_buttons)):
                    try:
                        async with page.expect_popup() as popup_info:
                            # Hämta knapparna igen för att undvika stale-fel
                            current_buttons = await page.locator("a:has-text('Matchinfo'), button:has-text('Matchinfo'), a:has-text('Live'), button:has-text('Live'), a[href*='match']").all()
                            await current_buttons[idx].click()
                        
                        popup = await popup_info.value
                        await popup.wait_for_load_state("networkidle")
                        await popup.wait_for_timeout(4000)

                        full_page_text = await popup.evaluate("() => document.body.innerText")
                        lines = full_page_text.split("\n")
                        
                        for line in lines:
                            line = line.strip()
                            # Letar efter mönstret för mål: [Namn] [Siffra] i slutet av raden
                            player_match = re.search(r'(?:\d+\s+)?([A-ZÅÄÖa-zåäö][-A-ZÅÄÖa-zåäö\s]+?)\s+(\d+)\s*$', line)
                            if player_match:
                                name = player_match.group(1).strip()
                                goals = int(player_match.group(2))
                                
                                if name in ["Matchinfo", "Resultat", "Domare", "Ledare", "Spelare", "Mål", "Lag", "Slutresultat", "Hemma", "Borta"] or len(name) < 5:
                                    continue
                                
                                if name not in stats_master[team['namn']]:
                                    stats_master[team['namn']][name] = {"Spelarnamn": name, "Matcher": 0, "Mål": 0, "Utvisningar": 0}
                                
                                stats_master[team['namn']][name]["Matcher"] += 1
                                stats_master[team['namn']][name]["Mål"] += goals

                            # Sök efter utvisningar
                            if "2'" in line or "2-min" in line:
                                for r_name in stats_master[team['namn']]:
                                    if r_name.lower() in line.lower():
                                        stats_master[team['namn']][r_name]["Utvisningar"] += 1
                        await popup.close()
                    except Exception as match_error:
                        print(f"Kunde inte läsa enskild match {idx}: {match_error}")
            except Exception as e:
                print(f"Kunde inte skrapa lag {team['namn']}: {e}")

        await browser.close()

        # Steg 3: Sortera spelarna efter flest gjorda mål
        final_data = {}
        for t_name in TARGET_TEAMS:
            final_data[t_name] = sorted(list(stats_master[t_name].values()), key=lambda x: x["Mål"], reverse=True)

        # Hämta dagens datum och tid
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Öppna och läs in basen för index.html som vi nyss skapade
        with open("index.html", "r", encoding="utf-8") as f:
            html_content = f.read()

        # Byt ut JavaScript-variablerna i HTML-filen mot den riktiga levande datan!
        # Detta ersätter de tomma objekten vi förberedde i index.html
        html_content = re.sub(r'const statsData = \{.*?\};', f'const statsData = {json.dumps(final_data, ensure_ascii=False)};', html_content)
        html_content = re.sub(r'const lastUpdated = ".*?";', f'const lastUpdated = "{now_str}";', html_content)

        # Spara tillbaka den uppdaterade datan till index.html
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"index.html har uppdaterats med levande matchdata kl. {now_str}!")

if __name__ == "__main__":
    asyncio.run(scrape_to_html_direct())
