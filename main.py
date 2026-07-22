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
from PIL import Image
import PIL
import pystray
from threading import Thread
from src.utils import set_config_value
import os
import sys

VERSION = "0.7.2"

GOOGLE_HOSTS = {"google.com","www.google.com","www.google.es","www.google.fr","www.google.de","www.google.co.uk","www.google.ca","www.google.com.au"}
BING_HOSTS = {"www.bing.com","bing.com"}

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
            if host in GOOGLE_HOSTS and urlparse(url).path == "/":
                #redirect to google_index.html
                flow.response = http.Response.make(
                    200,
                    (Path(__file__).parent/"html"/"google_index.html").read_bytes(),
                    {"Content-Type": "text/html; charset=utf-8"},
                )
                return
            
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

            if host in GOOGLE_HOSTS and flow.request.path == "/css/google_index.css":
                flow.response = http.Response.make(
                    200,
                    (Path(__file__).parent/"css"/"google_index.css").read_bytes(),
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
        image_path = Path(__file__).parent/"images"/"tray-icon.png"
        image = Image.open(image_path).convert("RGBA")
        
        if sys.platform == "darwin":
            import io
            import pystray._darwin as _pystray_darwin
            import AppKit,Foundation

            #hide dock icon, menu bar only
            AppKit.NSApplication.sharedApplication().setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

            def _retina_assert_image(self):
                #we need to resize the icon for retina displays, otherwise it will look pixelated
                thickness = self._status_bar.thickness()
                
                scale = AppKit.NSScreen.mainScreen().backingScaleFactor()
                px = int(thickness*scale)
                size = (px,px)

                if self._icon_image and self._icon_image.size() == (int(thickness),int(thickness)):
                    return

                source = PIL.Image.new("RGBA",size)
                source.paste(self._icon.resize(size,Image.LANCZOS))

                b = io.BytesIO()
                source.save(b,"png")
                data = Foundation.NSData(b.getvalue())

                ns_image = AppKit.NSImage.alloc().initWithData_(data)
                
                ns_image.setSize_(AppKit.NSSize(thickness,thickness))
                self._icon_image = ns_image
                self._status_item.button().setImage_(self._icon_image)

            _pystray_darwin.Icon._assert_image = _retina_assert_image #hook for retina support
            image = Image.open(image_path).convert("RGBA")
        else:
            image = image.resize((64,64),getattr(Image,"Resampling",Image).LANCZOS)

        thread = Thread(target=lambda: asyncio.run(start_proxy(config.general.host,config.general.port)))
        thread.start()
        
        def on_exit(icon,item):
            icon.stop()
            os._exit(0)

        icon = pystray.Icon("legacyProxy",image,"legacyProxy",menu=pystray.Menu(
            pystray.MenuItem(f"legacyProxy {VERSION} - {config.general.host}:{config.general.port}",lambda: None,enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Host...",lambda: set_config_value("general","host",config)),
            pystray.MenuItem("Port...",lambda: set_config_value("general","port",config)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Chrome Headless",lambda: set_config_value("general","chrome_headless",config),checked=lambda item: config.general.chrome_headless),
            pystray.MenuItem("Chrome Path...",lambda: set_config_value("general","chrome_path",config)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Google",lambda: set_config_value("services","google",config),checked=lambda item: config.services.google),
            pystray.MenuItem("Reddit",lambda: set_config_value("services","reddit",config),checked=lambda item: config.services.reddit),
            pystray.MenuItem("Wikipedia",lambda: set_config_value("services","wikipedia",config),checked=lambda item: config.services.wikipedia),
            pystray.MenuItem("GitHub",lambda: set_config_value("services","github",config),checked=lambda item: config.services.github),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit",on_exit)
        ))
        icon.run()
    except KeyboardInterrupt:
        pass
