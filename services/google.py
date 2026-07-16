import asyncio
from pathlib import Path
from time import monotonic
from urllib.parse import parse_qs,urlencode,urlparse
from patchright.async_api import async_playwright
import bs4

TEMPLATE_PATH = Path(__package__).parent/"html"/"google.html"
IMAGE_TEMPLATE_PATH = Path(__package__).parent/"html"/"google_imgs.html"
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
        self.image_cache = {}
        self.html_template = TEMPLATE_PATH.read_text(encoding="utf-8")
        self.image_home = IMAGE_TEMPLATE_PATH.read_text(encoding="utf-8")

    async def start(self):
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
        tbm = parse_qs(urlparse(url).query).get("tbm",[""])[0]
        if not query:
            return []

        cache_key = (query,tbm)
        cached = self.cache.get(cache_key)
        if cached and monotonic()-cached[0] < CACHE_TTL_SECONDS:
            print(f"using cached Google results for: {query}")
            return cached[1]

        async with self.lock:
            cached = self.cache.get(cache_key)
            if cached and monotonic()-cached[0] < CACHE_TTL_SECONDS:
                return cached[1]

            await self.start()
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

            search_params = {"q": query}
            if tbm == "isch":
                search_params["udm"] = "2"
            await self.page.goto(
                "https://www.google.com/search?"+urlencode(search_params),
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await self.page.wait_for_function(
                """params =>
                    location.pathname.indexOf('/sorry') === 0 ||
                    (
                        new URL(location.href).searchParams.get('q') === params.query &&
                        (
                            !params.images ||
                            new URL(location.href).searchParams.get('tbm') === 'isch' ||
                            new URL(location.href).searchParams.get('udm') === '2'
                        )
                    )
                """,
                arg={"query": query,"images": tbm == "isch"},
                timeout=30000,
            )
            await self.page.wait_for_load_state("domcontentloaded")
            if await self._captcha_present():
                raise GoogleCaptchaError(
                    "google requires a manual captcha in the patchright window"
                )
            if tbm == "isch":
                return await self.image_results(query,cache_key)

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
            self._set_search_tabs(soup,query)
            
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
            self.cache[cache_key] = (monotonic(),html_results)
            
            return html_results

    async def image_results(self,query,cache_key):
        images = self.page.locator(
            'img.YQ4gaf,img[src*="encrypted-tbn"],img[data-src*="encrypted-tbn"],'
            'a[href*="imgurl="] img,a[href*="imgrefurl="] img,a[href^="/imgres"] img'
        )
        await images.first.wait_for(timeout=30000)
        candidate_count = await images.count()
        results = await images.evaluate_all(
            """
            images => images.flatMap(image => {
                const src = image.getAttribute("data-src") || image.currentSrc || image.src
                const card = image.closest("[data-id]") || image.parentElement
                const anchor = image.closest("a[href]") || card?.querySelector("a[href]")
                let imageUrl = src
                let link = anchor?.href || src
                let anchorUrl = null
                try {
                    anchorUrl = new URL(link)
                    if (!imageUrl?.startsWith("http")) {
                        imageUrl = anchorUrl.searchParams.get("imgurl") || imageUrl
                    }
                    link = anchorUrl.searchParams.get("imgrefurl") ||
                        anchorUrl.searchParams.get("url") ||
                        link
                } catch (_) {}
                let sourceHost = ""
                try {
                    sourceHost = new URL(imageUrl).hostname
                } catch (_) {}
                const isResult =
                    image.classList.contains("YQ4gaf") ||
                    sourceHost.startsWith("encrypted-tbn") ||
                    anchorUrl?.pathname === "/imgres" ||
                    anchorUrl?.searchParams.has("imgurl") ||
                    anchorUrl?.searchParams.has("imgrefurl")
                if (
                    !imageUrl ||
                    !imageUrl.startsWith("http") ||
                    !isResult ||
                    image.closest("header,nav,form,[role=banner],[role=navigation]")
                ) return []

                return [{
                    image: imageUrl,
                    link: link,
                    title: image.alt || image.getAttribute("aria-label") || "",
                }]
            })
            """
        )
        print(
            f"Google Images candidates for {query}: "
            f"{candidate_count}, accepted: {len(results)}"
        )

        soup = bs4.BeautifulSoup(self.image_home,"html.parser")
        results_container = soup.find(id="results")
        soup.find("input",attrs={"name":"q"})["value"] = query
        self._set_search_tabs(soup,query,True)
        seen = set()

        for result in results:
            if result["image"] in seen:
                continue
            seen.add(result["image"])

            result_div = soup.new_tag("div",**{"class":"image-result"})
            result_a = soup.new_tag("a",href=result["link"])
            result_img = soup.new_tag(
                "img",
                src="/legacy-proxy-google-image?"+urlencode({"url":result["image"]}),
                alt=result["title"],
            )
            result_a.append(result_img)
            result_div.append(result_a)
            if result["title"]:
                title = soup.new_tag("p")
                title.string = result["title"]
                result_div.append(title)
            results_container.append(result_div)

        html_results = str(soup)
        if seen:
            self.cache[cache_key] = (monotonic(),html_results)
        return html_results

    def _set_search_tabs(self,soup,query,images=False):
        tabs = soup.select(".search-tab")
        tabs[0]["href"] = "/search?"+urlencode({"q":query})
        tabs[1]["href"] = "/search?"+urlencode({"q":query,"tbm":"isch"})
        for tab in tabs:
            tab["class"] = [name for name in tab.get("class",[]) if name != "active"]
        tabs[1 if images else 0]["class"].append("active")

    async def fetch_image(self,url):
        cached = self.image_cache.get(url)
        if cached:
            return cached

        await self.start()
        response = await self.context.request.get(
            url,
            headers={
                "Accept": "image/jpeg,image/png,image/gif,image/*;q=0.8,*/*;q=0.5",
                "Referer": "https://www.google.com/",
            },
            timeout=30000,
        )
        content_type = response.headers.get("content-type","").split(";",1)[0]
        if not response.ok or not content_type.startswith("image/"):
            print(
                f"Google image fetch failed: {response.status} "
                f"{content_type or 'unknown'} {url}"
            )
            return None

        image = (await response.body(),content_type)
        self.image_cache[url] = image
        return image
        
    async def close(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        self.context = None
        self.page = None
        self.playwright = None
