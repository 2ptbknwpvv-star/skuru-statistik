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
        # Kör dolt i bakgrunden
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

        # Fallback om den dynamiska sökningen misslyckas i molnmiljön
        if not resolved_teams:
            print("\n[Varning] Använder fasta reservlänkar...")
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
                print(f"Kunde inte öppna spelschema för {team['namn']}: {e}")
                continue
            
            # Identifiera alla spelade matcher ("Live Matchinfo"-knappar)
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
                    await popup.wait_for_timeout(4000)

                    # Ny mer specifik söklogik för Profixios laguppställningstabeller (både tr-rader och div-block)
                    player_elements = await popup.locator("tr:has(td), div.player-row, .game-person-row").all()
                    
                    for elem in player_elements:
                        text = await elem.inner_text()
                        if not text:
                            continue
                        
                        # Dela upp texten per rad/tabb för att hitta namn och siffror
                        parts = [p.strip() for p in text.split("\n") if p.strip()]
                        if len(parts) == 0:
                            parts = [p.strip() for p in text.split("\t") if p.strip()]

                        # Letar efter namn i textblocken
                        name = ""
                        for part in parts:
                            if re.match(r'^[A-ZÅÄÖa-zåäö][-A-ZÅÄÖa-zåäö\s]+$', part) and len(part) > 3:
                                if part not in ["Matchinfo", "Resultat", "Domare", "Ledare", "Spelare", "Mål", "Lag"]:
                                    name = part
                                    break
                        
                        if not name:
                            continue

                        # Skapa spelaren om den inte finns i vårt register
                        if name not in stats_master[team['namn']]:
                            stats_master[team['namn']][name] = {"Matcher": 0, "Mål": 0, "Utvisningar": 0}
                        
                        stats_master[team['namn']][name]["Matcher"] += 1
                        
                        # Sök efter mål (M) och utvisningar (2') i textsträngarna
                        full_line = " ".join(parts)
                        
                        # Försök hitta mål: Letar efter mönster som "M: X" eller kollar siffror i kolumnerna
                        goals_match = re.search(r'(?:Mål|M):\s*(\d+)', full_line, re.IGNORECASE)
                        if goals_match:
                            stats_master[team['namn']][name]["Mål"] += int(goals_match.group(1))
                        else:
                            # Sekundär koll om mål bara står som en siffra i slutet av raden
                            digits = re.findall(r'\d+', full_line)
                            if len(digits) >= 2: # Ofta [Tröjnummer, Mål]
                                stats_master[team['namn']][name]["Mål"] += int(digits[1])

                        # Försök hitta 2-minutersutvisningar (2')
                        p2_match = re.search(r"(?:2'|2min):\s*(\d+)", full_line, re.IGNORECASE)
                        if p2_match:
                            stats_master[team['namn']][name]["Utvisningar"] += int(p2_match.group(1))
                        elif "2'" in full_line:
                            # Räkna antal förekomster av 2'-tecknet om det står per händelse
                            stats_master[team['namn']][name]["Utvisningar"] += full_line.count("2'")

                    await popup.close()
                    await page.wait_for_timeout(1000)

                except Exception as e:
                    print(f"  Kunde inte läsa match {idx + 1}: {e}")
                    continue

        await browser.close()

        # --- Steg 3: Skapa Excel-filen med alla flikar ---
        output_file = "profixio_handbollsstatistik_auto.xlsx"
        with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
            
            # Statusflik
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            df_status = pd.DataFrame([{"Senast uppdaterad": now_str, "Status": "Slutförd"}])
            df_status.to_excel(writer, sheet_name="Info & Status", index=False)
            
            # Skapa flikar för lagen
            for team_name in TARGET_TEAMS:
                players = stats_master.get(team_name, {})
                if players:
                    df_team = pd.DataFrame.from_dict(players, orient='index')
                    df_team.index.name = 'Spelarnamn'
                    df_team.reset_index(inplace=True)
                    df_team = df_team.sort_values(by="Mål", ascending=False)
                else:
                    # Skapa en tom strukturerad tabell om laget inte har hunnit få data än
                    df_team = pd.DataFrame(columns=["Spelarnamn", "Matcher", "Mål", "Utvisningar"])
                
                df_team.to_excel(writer, sheet_name=team_name[:31], index=False)
                print(f"Sparade flik för: {team_name}")
        
        print(f"\nGenereringen är klar!")

if __name__ == "__main__":
    asyncio.run(scrape_to_excel_auto_urls())
