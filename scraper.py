import asyncio
from playwright.async_api import async_playwright
import pandas as pd
import re
from datetime import datetime

# Länk till ligans huvudsida (Säsongen 2026-27)
COMPETITION_URL = "https://profixio.com"

# De exakta lagnamnen som roboten ska söka efter och skapa flikar för
TARGET_TEAMS = ["Skuru IK 4", "Skuru IK 2", "Skuru IK 1"]

async def scrape_to_excel_auto_urls():
    async with async_playwright() as p:
        # Startar i headless=True för att kunna köras automatiskt i molnet/bakgrunden
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

        # Sök efter laglänkar i systemet
        for team_name in TARGET_TEAMS:
            try:
                # Letar efter länk som matchar lagnamnet i texten
                team_link_locator = page.locator(f"a:has-text('{team_name}')")
                if await team_link_locator.count() > 0:
                    href = await team_link_locator.first.get_attribute("href")
                    if href:
                        full_url = href if href.startswith("http") else f"https://profixio.com{href}"
                        if "t=schedule" not in full_url:
                            full_url += "&t=schedule&f=played" if "?" in full_url else "?t=schedule&f=played"
                        
                        resolved_teams.append({"namn": team_name, "url": full_url})
                        print(f"Hittade länk för {team_name}: {full_url}")
            except Exception as e:
                print(f"Kunde inte hitta URL automatiskt för {team_name}: {e}")

        # Fallback om den dynamiska sökningen misslyckas i molnmiljön
        if not resolved_teams:
            print("\n[Varning] Kunde inte hämta URL:er dynamiskt, använder fasta reservlänkar...")
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
                await page.wait_for_timeout(4000)
            except Exception as e:
                print(f"Kunde inte öppna spelschema för {team['namn']}: {e}")
                continue
            
            # Identifiera alla spelade matcher ("Live Matchinfo"-knappar)
            match_buttons = await page.locator("a:has-text('Live Matchinfo'), button:has-text('Live Matchinfo')").all()
            total_matches = len(match_buttons)
            print(f"Hittade {total_matches} spelade matcher.")

            for idx in range(total_matches):
                try:
                    print(f"  Öppnar matchprotokoll {idx + 1} av {total_matches}...")
                    
                    # Fånga upp popup-fönstret med matchbladet
                    async with page.expect_popup() as popup_info:
                        current_buttons = await page.locator("a:has-text('Live Matchinfo'), button:has-text('Live Matchinfo')").all()
                        await current_buttons[idx].click()
                    
                    popup = await popup_info.value
                    await popup.wait_for_load_state()
                    await popup.wait_for_timeout(3000)

                    # Skrapa ur statistiktabellerna från matchbladet
                    rows = await popup.locator("table tr").all()
                    for row in rows:
                        text = await row.inner_text()
                        if not text:
                            continue
                        
                        parts = text.split("\t")
                        if len(parts) >= 3:
                            name = parts[1].strip() if len(parts) > 1 else parts[0].strip()
                            
                            # Filtrera bort rubriker och ledartexter
                            if name in ["Namn", "Mål", "Lag", "Ledare", "Spelare"] or len(name) < 3:
                                continue
                            
                            if name not in stats_master[team['namn']]:
                                stats_master[team['namn']][name] = {"Matcher": 0, "Mål": 0, "Utvisningar": 0}
                            
                            stats_master[team['namn']][name]["Matcher"] += 1
                            
                            try:
                                # Söker efter gjorda mål i raden
                                goals = int(re.search(r'\d+', parts[2]).group()) if len(parts) > 2 else 0
                                stats_master[team['namn']][name]["Mål"] += goals
                            except:
                                pass

                    await popup.close()
                    await page.wait_for_timeout(1000)

                except Exception as e:
                    print(f"  Kunde inte läsa match {idx + 1}: {e}")
                    continue

        await browser.close()

        # --- Steg 3: Skapa Excel-filen med statistik och tidsstämpel ---
        output_file = "profixio_handbollsstatistik_auto.xlsx"
        with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
            
            # Flik 1: Statusflik med tidsstämpel för när insamlingen kördes
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            df_status = pd.DataFrame([{"Senast uppdaterad": now_str, "Status": "Slutförd utan fel"}])
            df_status.to_excel(writer, sheet_name="Info & Status", index=False)
            
            # Lagflikar
            for team_name, players in stats_master.items():
                if players:
                    df_team = pd.DataFrame.from_dict(players, orient='index')
                    df_team.index.name = 'Spelarnamn'
                    df_team.reset_index(inplace=True)
                    
                    # Sortera spelarna efter flest gjorda mål
                    df_team = df_team.sort_values(by="Mål", ascending=False)
                    df_team.to_excel(writer, sheet_name=team_name[:31], index=False)
                    print(f"Skapade Excel-flik för: {team_name}")
        
        print(f"\nGenereringen är klar! Filen sparades som '{output_file}'")

if __name__ == "__main__":
    asyncio.run(scrape_to_excel_auto_urls())
