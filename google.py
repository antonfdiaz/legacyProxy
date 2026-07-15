import asyncio
from pathlib import Path
from time import monotonic
from urllib.parse import parse_qs,urlparse
from patchright.async_api import async_playwright
import bs4

TEMPLATE_PATH = Path(__file__).parent/"html"/"google.html"
PROFILE_PATH = Path.home()/".legacyProxy-google-profile"
CHROME_PATH = Path("/Applications/Google Chrome.app")
CACHE_TTL_SECONDS = 300

class GoogleCaptchaError(RuntimeError):
    pass

class GoogleScraper:
    def __init__(self):
        self.playwright = None
        self.context = None
        self.page = None
        self.lock = asyncio.Lock()
        self.cache = {}
        self.html_template = TEMPLATE_PATH.read_text(encoding="utf-8")

    async def _start(self):
        if self.context:
            return

        self.playwright = await async_playwright().start()
        launch_options = {
            "user_data_dir": str(PROFILE_PATH),
            "headless": False,
            "no_viewport": True,
            "chromium_sandbox": True,
        }
        if CHROME_PATH.exists():
            launch_options["channel"] = "chrome"

        self.context = await self.playwright.chromium.launch_persistent_context(
            **launch_options
        )
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

    async def _captcha_present(self):
        if "/sorry/" in self.page.url:
            return True
        return bool(await self.page.locator(
            'iframe[src*="recaptcha"],#captcha,form[action*="/sorry/"]'
        ).count())

    async def search(self,url):
        query = parse_qs(urlparse(url).query).get("q",[""])[0]
        if not query:
            return []

        cached = self.cache.get(query)
        if cached and monotonic()-cached[0] < CACHE_TTL_SECONDS:
            print(f"using cached Google results for: {query}")
            return cached[1]

        async with self.lock:
            cached = self.cache.get(query)
            if cached and monotonic()-cached[0] < CACHE_TTL_SECONDS:
                return cached[1]

            await self._start()
            if await self._captcha_present():
                raise GoogleCaptchaError(
                    "Google requires a manual CAPTCHA in the Patchright window"
                )

            if self.page.url == "about:blank":
                await self.page.goto(
                    "https://www.google.com/",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )

                for label in ("Aceptar todo","Accept all"):
                    button = self.page.get_by_role("button",name=label)
                    if await button.count():
                        await button.first.click()
                        break

            search_box = self.page.locator("textarea[name=q],input[name=q]").first
            await search_box.fill(query)
            await search_box.press("Enter")
            await self.page.wait_for_function(
                """query =>
                    location.pathname.indexOf('/sorry') === 0 ||
                    new URL(location.href).searchParams.get('q') === query
                """,
                arg=query,
                timeout=30000,
            )
            await self.page.wait_for_load_state("domcontentloaded")
            if await self._captcha_present():
                raise GoogleCaptchaError(
                    "google requires a manual captcha in the patchright window"
                )
            await self.page.locator("h3").first.wait_for(timeout=30000)
            
            results = await self.page.locator("h3").evaluate_all(
                """
                titles => titles.flatMap(title => {
                    const link = title.closest("a")
                    if (!link) return []

                    const result = title.closest(".MjjYud") || title.closest(".g")
                    const snippet = result?.querySelector(
                        ".VwiC3b,.aCOpRe,.IsZvec"
                    )
                    return [{
                        title: title.innerText.trim(),
                        link: link.href,
                        snippet: snippet?.innerText.trim() || "",
                    }]
                })
                """
            )
            
            #generate html from template in ./html/google.html
            soup = bs4.BeautifulSoup(self.html_template,"html.parser")
            results_container = soup.find(id="results")
            soup.find("input",attrs={"name":"q"})["value"] = query
            
            for result in results:
                result_div = soup.new_tag("div",**{"class":"result"})
                title_h3 = soup.new_tag("h3")
                title_a = soup.new_tag("a",href=result["link"])
                title_a.string = result["title"]
                title_h3.append(title_a)
                domain = soup.new_tag("cite")
                domain.string = urlparse(result["link"]).netloc.removeprefix("www.")
                snippet_p = soup.new_tag("p")
                snippet_p.string = result["snippet"]
                result_div.append(title_h3)
                result_div.append(domain)
                result_div.append(snippet_p)
                results_container.append(result_div)
                
            html_results = str(soup)
            self.cache[query] = (monotonic(),html_results)
            
            return html_results
        
    async def close(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        self.context = None
        self.page = None
        self.playwright = None
