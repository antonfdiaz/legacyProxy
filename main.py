from mitmproxy import http,options
from mitmproxy.tools.dump import DumpMaster
from src.services.github import GitHubProxy
from src.services.google import GoogleCaptchaError,GoogleScraper
from src.services.reddit import RedditProxy
from src.services.wikipedia import WikipediaProxy
from src.config import Config
import asyncio
from pathlib import Path
from urllib.parse import parse_qs,urlparse

VERSION = "0.6.0"

GOOGLE_HOSTS = {"www.google.com","www.google.es","www.google.fr","www.google.de","www.google.co.uk","www.google.ca","www.google.com.au"}

config = Config()

class InterceptAddon:
    def __init__(self):
        self.config = config or Config()
        
        #initialize proxy services
        self.github = GitHubProxy() if config.services.github else None
        self.google = GoogleScraper(
            chrome_headless=self.config.general.chrome_headless) if config.services.google else None
        self.reddit = RedditProxy() if config.services.reddit else None
        self.wikipedia = WikipediaProxy() if config.services.wikipedia else None

    async def request(self,flow):
        host = flow.request.pretty_host
        url = flow.request.url
        
        if self.google:
            if host in GOOGLE_HOSTS and urlparse(url).path == "/legacy-proxy-google-image":
                image_url = parse_qs(urlparse(url).query).get("url",[""])[0]
                if urlparse(image_url).scheme in {"http","https"}:
                    image = await self.google.fetch_image(image_url)
                    if image:
                        content,content_type = image
                        flow.response = http.Response.make(
                            200,
                            content,
                            {
                                "Content-Type": content_type,
                                "Cache-Control": "public,max-age=86400",
                            },
                        )
                    else:
                        flow.response = http.Response.make(404,b"")
                    return

            if host in GOOGLE_HOSTS and flow.request.path == "/images/google.png":
                flow.response = http.Response.make(
                    200,
                    (Path(__file__).parent/"images"/"google.png").read_bytes(),
                    {"Content-Type": "image/png","Cache-Control": "public,max-age=86400"},
                )
                return
            
            if host in GOOGLE_HOSTS and flow.request.path == "/css/google.css":
                flow.response = http.Response.make(
                    200,
                    (Path(__file__).parent/"css"/"google.css").read_bytes(),
                    {"Content-Type": "text/css","Cache-Control": "public,max-age=86400"},
                )
                return

            if host in GOOGLE_HOSTS and flow.request.path == "/css/google_imgs.css":
                flow.response = http.Response.make(
                    200,
                    (Path(__file__).parent/"css"/"google_imgs.css").read_bytes(),
                    {"Content-Type": "text/css","Cache-Control": "public,max-age=86400"},
                )
                return
            
            if host in GOOGLE_HOSTS and flow.request.path == "/js/google.js":
                flow.response = http.Response.make(
                    200,
                    (Path(__file__).parent/"js"/"google.js").read_bytes(),
                    {"Content-Type": "application/javascript","Cache-Control": "public,max-age=86400"},
                )
                return

            if host in GOOGLE_HOSTS and flow.request.path.startswith("/imghp"):
                flow.response = http.Response.make(
                    200,
                    self.google.image_home.encode("utf-8"),
                    {"Content-Type": "text/html; charset=utf-8"},
                )
                return

            if host in GOOGLE_HOSTS and flow.request.path.startswith("/search?"):
                print(f"[INFO] intercepting Google search: {url}")
                try:
                    content = (await self.google.search(url)).encode("utf-8")
                    flow.response = http.Response.make(
                        200,
                        content,
                        {"Content-Type": "text/html; charset=utf-8"},
                    )
                except GoogleCaptchaError as e:
                    print(f"[WARN] Google CAPTCHA detected: {e}")
                    flow.response = http.Response.make(
                        503,
                        (
                            "<!doctype html><meta charset=utf-8>"
                            "<title>Google CAPTCHA</title>"
                            "<p>Oops. Google needs a CAPTCHA! Try again later.</p>"
                        ).encode("utf-8"),
                        {"Content-Type": "text/html; charset=utf-8"},
                    )
                except Exception as e:
                    detail = f"{type(e).__name__}: {e}"
                    print(f"[ERROR] Google intercept failed: {detail}")
                    flow.response = http.Response.make(
                        500,
                        (
                            "<!doctype html><meta charset=utf-8>"
                            "<title>Google Intercept Failed</title>"
                            f"<p>{detail}</p>"
                        ).encode("utf-8"),
                        {"Content-Type": "text/html; charset=utf-8"},
                    )
                
        if self.reddit and self.reddit.request(flow):
            return
        
        if self.wikipedia and self.wikipedia.request(flow):
            return
        
    def response(self,flow):
        #handle responses for proxy services
        self.github.response(flow) if self.github else None
        self.wikipedia.response(flow) if self.wikipedia else None
        self.reddit.response(flow) if self.reddit else None

        print(f"[INFO] intercepted response from: {flow.request.url}")

    async def close(self):
        await self.google.close()

async def start_proxy(host,port):
    opts = options.Options(listen_host=host,listen_port=port)
    opts.update_defer(tls_version_client_min="TLS1")
    master = DumpMaster(opts)
    addon = InterceptAddon()
    master.addons.add(addon)
    try:
        print(r""" _                               ___                     
| | ___  __ _  __ _  ___ _   _  / _ \_ __ _____  ___   _ 
| |/ _ \/ _` |/ _` |/ __| | | |/ /_)/ '__/ _ \ \/ / | | |
| |  __/ (_| | (_| | (__| |_| / ___/| | | (_) >  <| |_| |
|_|\___|\__, |\__,_|\___|\__, \/    |_|  \___/_/\_\\__, |
        |___/            |___/                     |___/""")
        print(f"legacyProxy v{VERSION} - MITM proxy for legacy iOS devices")
        print(f"[INFO] starting proxy at {host}:{port}...")
        await master.run()
    except KeyboardInterrupt:
        print("[INFO] stopping proxy...")
        master.shutdown()
    finally:
        print("[INFO] stopping proxy...")
        await addon.close()
        
if __name__ == "__main__":
    try:
        asyncio.run(start_proxy(config.general.host,config.general.port))
    except KeyboardInterrupt:
        pass
