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

        print("--- Söker efter laglänkar ---")
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

        if not resolved_teams:
            resolved_teams = [
                {"namn": "Skuru IK 4", "url": "https://profixio.com/teams/1598917?k=1183572&t=schedule&f=played"},
                {"namn": "Skuru IK 2", "url": "https://profixio.com/teams/1581327?k=1183570&t=schedule&f=played"},
                {"namn": "Skuru IK 1", "url": "https://profixio.com/teams/1581326?k=1183570&t=schedule&f=played"}
            ]

        print("--- Skrapar matcher ---")
        for team in resolved_teams:
            try:
                await page.goto(team["url"])
                await page.wait_for_timeout(5000)
                match_buttons = await page.locator("a:has-text('Matchinfo'), button:has-text('Matchinfo'), a:has-text('Live'), button:has-text('Live')").all()
                
                for idx in range(len(match_buttons)):
                    if idx >= 10: break # Säkerhetsspärr för demo
                    async with page.expect_popup() as popup_info:
                        await match_buttons[idx].click()
                    popup = await popup_info.value
                    await popup.wait_for_load_state("networkidle")
                    await popup.wait_for_timeout(4000)

                    full_page_text = await popup.evaluate("() => document.body.innerText")
                    lines = full_page_text.split("\n")
                    
                    for line in lines:
                        line = line.strip()
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

                        if "2'" in line or "2-min" in line:
                            for r_name in stats_master[team['namn']]:
                                if r_name.lower() in line.lower():
                                    stats_master[team['namn']][r_name]["Utvisningar"] += 1
                    await popup.close()
            except Exception as e:
                print(f"Kunde inte skrapa lag: {e}")

        await browser.close()

        # Gör om datan till listor för HTML-sidan
        final_data = {}
        for t_name in TARGET_TEAMS:
            final_data[t_name] = sorted(list(stats_master[t_name].values()), key=lambda x: x["Mål"], reverse=True)

        # Generera en helt ny, supersnygg index.html med datan inbäddad
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        html_content = f"""<!DOCTYPE html>
<html lang="sv">
<head>
    <meta charset="UTF-8">
    <title>Skuru IK Handbollsstatistik</title>
    <script src="https://jsdelivr.net"></script>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 900px; margin: 30px auto; padding: 20px; background-color: #f4f6f9; }}
        h1, h2 {{ color: #004b87; text-align: center; }}
        .update-tag {{ text-align: center; font-style: italic; color: #666; margin-bottom: 20px; }}
        .box {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 25px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
        th {{ background-color: #004b87; color: white; }}
        tr:nth-child(even) {{ background-color: #f9f9f9; }}
        button {{ background-color: #28a745; color: white; padding: 10px 20px; font-size: 16px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; width: 100%; margin-top: 10px; }}
        button:hover {{ background-color: #218838; }}
    </style>
</head>
<body>
    <h1>Skuru IK - Handbollsstatistik</h1>
    <div class="update-tag">Senast uppdaterad från Profixio: {now_str}</div>
    
    <div class="box">
        <h2>Ladda ner till Excel</h2>
        <p>Klicka på knappen nedan för att ladda ner all aktuell statistik direkt till en Excel-fil med flikar för varje lag.</p>
        <button onclick="downloadExcel()">📥 Ladda ner Excel-fil (.xlsx)</button>
    </div>

    <script>
        const statsData = {json.dumps(final_data)};

        function downloadExcel() {{
            const workbook = XLSX.utils.book_new();
            
            // Skapa statusflik
            const statusWS = XLSX.utils.json_to_sheet([({{"Senast uppdaterad": "{now_str}", "Status": "OK"}})]);
            XLSX.utils.book_append_sheet(workbook, statusWS, "Info & Status");
            
            // Skapa lagflikar
            for (const [teamName, players] of Object.entries(statsData)) {{
                if (players.length > 0) {{
                    const ws = XLSX.utils.json_to_sheet(players);
                    XLSX.utils.book_append_sheet(workbook, ws, teamName);
                }} else {{
                    const ws = XLSX.utils.json_to_sheet([({{"Spelarnamn": "Inga matcher skrapade än", "Matcher": 0, "Mål": 0, "Utvisningar": 0}})]);
                    XLSX.utils.book_append_sheet(workbook, ws, teamName);
                }}
            }}
            XLSX.writeFile(workbook, "Skuru_Handbollsstatistik.xlsx");
        }}
    </script>
</body>
</html>
"""
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        print("index.html har uppdaterats med färsk statistik!")

if __name__ == "__main__":
    asyncio.run(scrape_to_html_direct())
