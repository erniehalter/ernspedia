import os
import sys
import subprocess
from pathlib import Path

# --- SELF-BOOTSTRAP LOGIC ---
def bootstrap():
    if sys.prefix != sys.base_prefix: return
    script_dir = Path(__file__).parent.absolute()
    venv_dir = script_dir / "venv"
    venv_python = venv_dir / "bin" / "python"
    if not venv_dir.exists():
        print(f"[*] Creating virtual environment...")
        subprocess.run(["/opt/homebrew/bin/python3.12", "-m", "venv", str(venv_dir)], check=True)
    marker = venv_dir / ".deps_installed"
    if not marker.exists():
        print("[*] Installing dependencies...")
        subprocess.run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
        deps = ["curl_cffi==0.7.0b4", "playwright==1.50.0", "playwright-stealth==1.0.6", "loguru==0.7.2", "setuptools==75.8.2"]
        subprocess.run([str(venv_python), "-m", "pip", "install"] + deps, check=True)
        subprocess.run([str(venv_python), "-m", "playwright", "install", "chromium"], check=True)
        marker.touch()
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)

if __name__ == "__main__":
    if sys.prefix == sys.base_prefix: bootstrap()

# --- GHOST ENGINE ---
import asyncio
import json
import re
import time
import random
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from loguru import logger

class ExpediaEngine:
    def __init__(self):
        # Rotating User Agents to stay fresh
        self.ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"

    async def get_car_data(self, airport: str, d1: str, d2: str) -> list:
        async with async_playwright() as p:
            # 1. DEEP STEALTH LAUNCH
            # Stripping the --enable-automation flag is critical for Akamai
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars",
                    "--window-size=390,844"
                ],
                ignore_default_args=["--enable-automation"]
            )
            
            context = await browser.new_context(
                user_agent=self.ua,
                viewport={"width": 390, "height": 844},
                is_mobile=True,
                has_touch=True,
                locale="en-US",
                timezone_id="America/Los_Angeles"
            )
            
            page = await context.new_page()
            await stealth_async(page)

            try:
                # 2. THE "NATURAL ENTRY" (Land on home first)
                logger.info(f"Ghosting into Expedia for {airport}...")
                await page.goto("https://www.expedia.com/", wait_until="networkidle", timeout=60000)
                await asyncio.sleep(random.uniform(2, 4))
                
                # 3. NAVIGATE TO SEARCH (Deep Link)
                url = f"https://www.expedia.com/carsearch?locn={airport}&d1={d1}&d2={d2}&time1=10:00AM&time2=10:00AM"
                await page.goto(url, wait_until="domcontentloaded")
                
                # 4. HUMAN BEHAVIOR SIMULATION
                logger.info("Solving background challenges...")
                for _ in range(3):
                    await page.mouse.move(random.randint(100, 300), random.randint(100, 600))
                    await page.mouse.wheel(0, random.randint(200, 500))
                    await asyncio.sleep(random.uniform(1, 2))

                # 5. WAIT FOR DATA (Up to 30s)
                logger.info("Extracting deals...")
                found = False
                for i in range(15):
                    # Check for car cards OR the Apollo state in memory
                    check = await page.evaluate("() => !!document.querySelector('[data-testid=\"car-offer-card\"], a[aria-label*=\"Reserve\"]')")
                    if check:
                        found = True
                        break
                    if i == 5: # Halfway through, try a small scroll
                        await page.mouse.wheel(0, 1000)
                    await asyncio.sleep(2)
                
                if not found:
                    logger.warning(f"Results timed out for {airport}. Saving evidence.")
                    await page.screenshot(path=f"evidence_{airport}.png")
                    return []

                # 6. PULL RAW DATA
                data = await page.evaluate("() => window.__APOLLO_STATE__")
                if data:
                    return self._parse_apollo(data)
                else:
                    return await self._scrape_dom_fallback(page)

            except Exception as e:
                logger.error(f"Internal Error: {e}")
                return []
            finally:
                await browser.close()

    async def _scrape_dom_fallback(self, page) -> list:
        results = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('a[aria-label*="Reserve Item"]'))
                        .map(el => el.getAttribute('aria-label'));
        }''')
        offers = []
        for item in results:
            match = re.search(r'Reserve Item, (.*) from (.*) at \$(.*) total', item)
            if match:
                offers.append({"vendor": match[2].strip(), "vehicle": match[1].strip(), "total_price": f"${match[3].strip()}"})
        return offers

    def _parse_apollo(self, state: dict) -> list:
        offers = []
        for key, value in state.items():
            if value.get("__typename") == "LodgingCard":
                car_type = value.get("headingSection", {}).get("heading", "Unknown")
                price = "N/A"
                try:
                    price = value["priceSection"]["priceSummary"]["displayMessages"][0]["lineItems"][0]["price"]["formatted"]
                except: pass
                summary = value.get("summarySections", [{}])[0]
                vendor = summary.get("vendorLogo", {}).get("description", "Generic").replace(" Rental Company", "")
                offers.append({"vendor": vendor, "vehicle": car_type, "total_price": price})
        
        def s_key(x):
            try: return int(re.sub(r'[^\d]', '', x['total_price']))
            except: return 999999
        return sorted(offers, key=s_key)

async def main():
    engine = ExpediaEngine()
    print("\n" + "█" * 65)
    print(f" EXPEDIA INTELLIGENCE ENGINE | SEARCHING: LAX & SNA")
    print("█" * 65)
    
    for apt in ["LAX", "SNA"]:
        results = await engine.get_car_data(apt, "2026-04-01", "2026-04-05")
        if results:
            print(f"\n[+] SUCCESS: Found {len(results)} deals for {apt}")
            print(f"{'VENDOR':<20} | {'VEHICLE':<25} | {'TOTAL PRICE'}")
            print("-" * 65)
            for o in results[:5]:
                print(f"{o['vendor']:<20} | {o['vehicle']:<25} | {o['total_price']}")
        else:
            print(f"\n[!] FAILED: {apt} block. Check evidence_{apt}.png")
    print("\n" + "█" * 65 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
