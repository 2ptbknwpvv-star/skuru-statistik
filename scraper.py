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
        # Sätt webbläsaren till svenskt territorium och språk för att tvinga fram rätt menyer
        context = await browser.new_context(locale="sv-SE", timezone_id="Europe/Stockholm")
        page = await context.new_page()
        
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
                        full_url = href if href.startswith("http") else f"https://www.profixio.com{href}"
                        if "t=schedule" not in full_url:
                            full_url += "&t=schedule&f=played" if "?" in full_url else "?t=schedule&f=played"
                        else:
                            full_url = full_url.replace("f=upcoming", "f=played").replace("f=all", "f=played")
                        
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
            
            # Smart sökning efter knappar oavsett om de heter Matchinfo, Live, Info eller info-ikoner
            match_buttons = await page.locator("a[href*='match'], button:has-text('info'), a:has-text('info'), button:has-text('Live'), a:has-text('Live'), .profixio-match-link").all()
            if not match_buttons:
                # Bred sökning om profixio ändrat klasser helt
                match_buttons = await page.locator("text=/Matchinfo|Live|Info|Detajler/i").all()
                
            total_matches = len(match_buttons)
            print(f"Hittade {total_matches} matcher i listan.")

            for idx in range(total_matches):
                try:
                    print(f"  Öppnar matchprotokoll {idx + 1} av {total_matches}...")
                    
                    async with page.expect_popup() as popup_info:
                        await match_buttons[idx].click()
                    
                    popup = await popup_info.value
                    await popup.wait_for_load_state("networkidle")
                    await popup.wait_for_timeout(5000)

                    # Den ultimata textinsamlingen: Suger ut ALL text synlig på skärmen
                    full_page_text = await popup.evaluate("() => document.getSelection() ? document.body.innerText : document.body.textContent")
                    lines = full_page_text.split("\n")
                    
                    for line in lines:
                        line = line.strip()
                        if not line or len(line) < 4:
                            continue
                        
                        # Avancerad regex-matchning som fångar upp rader med [Nummer] [Spelarnamn] [Mål]
                        # Exempel: "12 Elin Östlund 5" eller "Malin Andersson 3"
                        player_match = re.search(r'(?:\d+\s+)?([A-ZÅÄÖa-zåäö][-A-ZÅÄÖa-zåäö\s]+?)\s+(\d+)\s*$', line)
                        if player_match:
                            name = player_match.group(1).strip()
                            goals = int(player_match.group(2))
                            
                            # Rensa bort falska träffar från menyer eller resultatblock
                            if name in ["Matchinfo", "Resultat", "Domare", "Ledare", "Spelare", "Mål", "Lag", "Period", "Slutresultat", "Hemma", "Borta", "Flickor", "F13", "Kvalificering"] or len(name) < 5:
                                continue
                            
                            if name not in stats_master[team['namn']]:
                                stats_master[team['namn']][name] = {"Matcher": 0, "Mål": 0, "Utvisningar": 0}
                            
                            stats_master[team['namn']][name]["Matcher"] += 1
                            stats_master[team['namn']][name]["Mål"] += goals

                        # Letar efter 2-minutersutvisningar (Letar efter namnet + symbolen 2')
                        if "2'" in line or "2min" in line or "Utvisning" in line:
                            for registered_name in stats_master[team['namn']]:
                                if registered_name.lower() in line.lower():
                                    stats_master[team['namn']][registered_name]["Utvisningar"] += 1

                    await popup.close()
                    await page.wait_for_timeout(1500)

                except Exception as e:
                    print(f"  Kunde inte skrapa match {idx + 1}: {e}")
                    continue

        await context.close()
        await browser.close()

        # --- Steg 3: Generera den färdiga Excel-filen ---
        output_file = "profixio_handbollsstatistik_auto.xlsx"
        with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
            
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            df_status = pd.DataFrame([{"Senast uppdaterad": now_str, "Status": "Slutförd med språksäkrad djupskrapning"}])
            df_status.to_excel(writer, sheet_name="Info & Status", index=False)
            
            for team_name in TARGET_TEAMS:
                players = stats_master.get(team_name, {})
                if players:
                    df_team = pd.DataFrame.from_dict(players, orient='index')
                    df_team.index.name = 'Spelarnamn'
                    df_team.reset_index(inplace=True)
                    df_team = df_team.sort_values(by="Mål", ascending=False)
                else:
                    # Skapar tomma korrekta kolumner om laget inte spelat några matcher ännu
                    df_team = pd.DataFrame(columns=["Spelarnamn", "Matcher", "Mål", "Utvisningar"])
                
                df_team.to_excel(writer, sheet_name=team_name[:31], index=False)
                print(f"Skapat flik för: {team_name}")
        
        print(f"\nAllt klart!")

if __name__ == "__main__":
    asyncio.run(scrape_to_excel_auto_urls())
