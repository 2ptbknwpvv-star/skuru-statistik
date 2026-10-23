import asyncio
from playwright.async_api import async_playwright
import pandas as pd
import re
from datetime import datetime

COMPETITION_URL = "https://profixio.com"
TARGET_TEAMS = ["Skuru IK 4", "Skuru IK 2", "Skuru IK 1"]

async def scrape_to_excel_auto_urls():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        resolved_teams = []
        stats_master = {}

        print("--- Steg 1: Hittar lagens unika URL-länkar automatiskt ---")
        try:
            await page.goto(COMPETITION_URL)
            await page.wait_for_timeout(4000)
        except Exception as e:
            print(f"Kunde inte ladda tävlingssidan: {e}")
            await browser.close()
            return

        for team_name in TARGET_TEAMS:
            try:
                team_link_locator = page.locator(f"a:has-text('{team_name}')")
                if await team_link_locator.count() > 0:
                    href = await team_link_locator.first.get_attribute("href")
                    if href:
                        full_url = href if href.startswith("http") else f"https://profixio.com{href}"
                        if "t=schedule" not in full_url:
                            full_url += "&t=schedule&f=played" if "?" in full_url else "?t=schedule&f=played"
                        else:
                            full_url = full_url.replace("f=upcoming", "f=played")
                        
                        resolved_teams.append({"namn": team_name, "url": full_url})
                        print(f"Hittade länk för {team_name}: {full_url}")
            except Exception as e:
                print(f"Kunde inte hitta URL för {team_name}: {e}")

        if not resolved_teams:
            resolved_teams = [
                {"namn": "Skuru IK 4", "url": "https://profixio.com/teams/1598917?k=1183572&t=schedule&f=played"},
                {"namn": "Skuru IK 2", "url": "https://profixio.com/teams/1581327?k=1183570&t=schedule&f=played"},
                {"namn": "Skuru IK 1", "url": "https://profixio.com/teams/1581326?k=1183570&t=schedule&f=played"}
            ]

        print("\n--- Steg 2: Skrapar matchprotokoll och samlar statistik ---")
        for team in resolved_teams:
            print(f"\nÖppnar spelschema för: {team['namn']}")
            stats_master[team['namn']] = {}
            
            try:
                await page.goto(team["url"])
                await page.wait_for_timeout(5000)
            except Exception as e:
                print(f"Kunde inte öppna spelschema: {e}")
                continue
            
            match_buttons = await page.locator("a:has-text('Matchinfo'), button:has-text('Matchinfo'), a:has-text('Live'), button:has-text('Live')").all()
            total_matches = len(match_buttons)
            print(f"Hittade {total_matches} matcher i listan.")

            for idx in range(total_matches):
                try:
                    print(f"  Öppnar matchprotokoll {idx + 1} av {total_matches}...")
                    
                    async with page.expect_popup() as popup_info:
                        current_buttons = await page.locator("a:has-text('Matchinfo'), button:has-text('Matchinfo'), a:has-text('Live'), button:has-text('Live')").all()
                        await current_buttons[idx].click()
                    
                    popup = await popup_info.value
                    await popup.wait_for_load_state()
                    await popup.wait_for_timeout(5000)

                    # Tvinga fram ALL råtext från hela fönstret (Ctrl+A metod)
                    full_page_text = await popup.evaluate("() => document.body.innerText")
                    lines = full_page_text.split("\n")
                    
                    for line in lines:
                        line = line.strip()
                        if not line or len(line) < 5:
                            continue
                        
                        # Regex-filter för att plocka rader som har: [Nummer/Tomt] [Namn Namnsson] [Mål/Utvisning]
                        # Detekterar handbollsrader som t.ex. "9 Anna Andersson 4" eller "Anna Andersson 2'"
                        match = re.search(r'(?:\d+\s+)?([A-ZÅÄÖa-zåäö][-A-ZÅÄÖa-zåäö\s]+?)\s+(\d+)\s*$', line)
                        if match:
                            name = match.group(1).strip()
                            goals = int(match.group(2))
                            
                            if name in ["Matchinfo", "Resultat", "Domare", "Ledare", "Spelare", "Mål", "Lag", "Period", "Slutresultat", "Hemma", "Borta"] or len(name) < 4:
                                continue
                            
                            if name not in stats_master[team['namn']]:
                                stats_master[team['namn']][name] = {"Matcher": 0, "Mål": 0, "Utvisningar": 0}
                            
                            stats_master[team['namn']][name]["Matcher"] += 1
                            stats_master[team['namn']][name]["Mål"] += goals

                        # Sök efter utvisningar på samma rad
                        if "2'" in line or "2-min" in line:
                            for name_check in stats_master[team['namn']]:
                                if name_check in line:
                                    stats_master[team['namn']][name_check]["Utvisningar"] += line.count("2'")

                    await popup.close()
                    await page.wait_for_timeout(1000)

                except Exception as e:
                    print(f"  Kunde inte läsa match {idx + 1}: {e}")
                    continue

        await browser.close()

        # --- Steg 3: Skapa Excel-filen ---
        output_file = "profixio_handbollsstatistik_auto.xlsx"
        with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
            
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            df_status = pd.DataFrame([{"Senast uppdaterad": now_str, "Status": "Slutförd med djupskrapning"}])
            df_status.to_excel(writer, sheet_name="Info & Status", index=False)
            
            for team_name in TARGET_TEAMS:
                players = stats_master.get(team_name, {})
                if players:
                    df_team = pd.DataFrame.from_dict(players, orient='index')
                    df_team.index.name = 'Spelarnamn'
                    df_team.reset_index(inplace=True)
                    df_team = df_team.sort_values(by="Mål", ascending=False)
                else:
                    df_team = pd.DataFrame(columns=["Spelarnamn", "Matcher", "Mål", "Utvisningar"])
                
                df_team.to_excel(writer, sheet_name=team_name[:31], index=False)
                print(f"Skapat flik för: {team_name}")
        
        print(f"\nKörningen är klar!")

if __name__ == "__main__":
    asyncio.run(scrape_to_excel_auto_urls())
