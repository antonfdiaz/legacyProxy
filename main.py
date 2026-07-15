from mitmproxy import http,options
from mitmproxy.tools.dump import DumpMaster
from google import GoogleCaptchaError,GoogleScraper
import asyncio
import re
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit

GOOGLE_HOSTS = {"www.google.com","www.google.es","www.google.fr","www.google.de","www.google.co.uk","www.google.ca","www.google.com.au"}
REDDIT_HOSTS = {"reddit.com","www.reddit.com"}
REDDIT_MOBILE_CSS = f"""
<style id="legacy-proxy-mobile">
{open(Path(__file__).parent/"css"/"reddit.css","r",encoding="utf-8").read()}
</style>
"""
WIKIPEDIA_HOSTS = {"en.wikipedia.org","es.wikipedia.org","fr.wikipedia.org","de.wikipedia.org"}

class InterceptAddon:
    def __init__(self):
        self.google = GoogleScraper()

    async def request(self,flow):
        print(f"Intercepted request to: {flow.request.url}")
        host = flow.request.pretty_host
        url = flow.request.url

        if host in GOOGLE_HOSTS and flow.request.path == "/images/google.png":
            flow.response = http.Response.make(
                200,
                (Path(__file__).parent/"images"/"google.png").read_bytes(),
                {"Content-Type": "image/png","Cache-Control": "public,max-age=86400"},
            )
            return
        
        if host in GOOGLE_HOSTS and flow.request.path == "/images/search.png":
            flow.response = http.Response.make(
                200,
                (Path(__file__).parent/"images"/"search.png").read_bytes(),
                {"Content-Type": "image/png","Cache-Control": "public,max-age=86400"},
            )
            return
        
        if host in GOOGLE_HOSTS and flow.request.path == "/images/loader.gif":
            flow.response = http.Response.make(
                200,
                (Path(__file__).parent/"images"/"loader.gif").read_bytes(),
                {"Content-Type": "image/gif","Cache-Control": "public,max-age=86400"},
            )
            return
        
        if host in GOOGLE_HOSTS and flow.request.path == "/css/google.css":
            flow.response = http.Response.make(
                200,
                (Path(__file__).parent/"css"/"google.css").read_bytes(),
                {"Content-Type": "text/css","Cache-Control": "public,max-age=86400"},
            )
            return

        if (
            host in WIKIPEDIA_HOSTS
            and flow.request.path.startswith("/legacy-proxy-wikipedia-image/")
        ):
            image_parts = urlsplit(url)
            image_path = "/"+image_parts.path[len("/legacy-proxy-wikipedia-image/"):]
            flow.request.url = urlunsplit(
                ("https","upload.wikimedia.org",image_path,image_parts.query,"")
            )
            flow.request.headers["Accept"] = "image/jpeg,image/png,image/*;q=0.8,*/*;q=0.5"
            return

        if host in GOOGLE_HOSTS and flow.request.path.startswith("/search?"):
            print(f"intercepting Google search: {url}")
            try:
                content = (await self.google.search(url)).encode("utf-8")
                flow.response = http.Response.make(
                    200,
                    content,
                    {"Content-Type": "text/html; charset=utf-8"},
                )
            except GoogleCaptchaError as e:
                print(f"google CAPTCHA detected: {e}")
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
                print(f"google intercept failed: {detail}")
                
        parts = urlsplit(url)
        if host == "old.reddit.com" and parts.path.startswith("/legacy-proxy-image/"):
            image_path = "/"+parts.path[len("/legacy-proxy-image/"):]
            flow.request.url = urlunsplit(
                ("https","preview.redd.it",image_path,parts.query,"")
            )
            flow.request.headers["Accept"] = "image/jpeg,image/png,image/*;q=0.8,*/*;q=0.5"
            return

        if host in REDDIT_HOSTS|{"old.reddit.com"} and parts.path.startswith("/gallery/"):
            gallery_id = parts.path[len("/gallery/"):].split("/",1)[0]
            if gallery_id:
                redirect_url = urlunsplit(
                    (parts.scheme,"old.reddit.com",f"/comments/{gallery_id}",parts.query,parts.fragment)
                )
                flow.response = http.Response.make(
                    302,
                    b"",
                    {"Location": redirect_url,"Cache-Control": "no-store"},
                )
                return

        if host in REDDIT_HOSTS:
            print(f"intercepting Reddit request: {url}")
            redirect_url = urlunsplit(
                (parts.scheme,"old.reddit.com",parts.path,parts.query,parts.fragment)
            )
            flow.response = http.Response.make(
                302,
                b"",
                {"Location": redirect_url,"Cache-Control": "no-store"},
            )
            return
        
    def response(self,flow):
        content_type = flow.response.headers.get("Content-Type","")
        if flow.request.pretty_host in WIKIPEDIA_HOSTS and "text/html" in content_type:
            html = flow.response.text
            image_prefix = (
                "https://"+flow.request.pretty_host+"/legacy-proxy-wikipedia-image/"
            )
            html = html.replace("https://upload.wikimedia.org/",image_prefix)
            html = html.replace("//upload.wikimedia.org/",image_prefix)
            html = re.sub(
                r'\s+(?:srcset|loading|decoding)=(?:"[^"]*"|\'[^\']*\')',
                "",
                html,
                flags=re.IGNORECASE,
            )
            flow.response.text = html

        if flow.request.pretty_host == "old.reddit.com" and "text/html" in content_type:
            html = flow.response.text
            html = re.sub(
                r'<link\b(?=[^>]*\bref=["\']applied_subreddit_stylesheet["\'])[^>]*>',
                "",
                html,
                count=1,
                flags=re.IGNORECASE,
            )
            html = html.replace(
                '<meta name="viewport" content="width=1024">',
                '<meta name="viewport" content="width=device-width,initial-scale=1.0">',
                1,
            )
            html = html.replace(
                "https://preview.redd.it/",
                "https://old.reddit.com/legacy-proxy-image/",
            )
            html = html.replace(
                "//preview.redd.it/",
                "https://old.reddit.com/legacy-proxy-image/",
            )
            html = html.replace("</head>",REDDIT_MOBILE_CSS+"</head>",1)
            flow.response.text = html

        print(f"intercepted response from: {flow.request.url}")

    async def close(self):
        await self.google.close()

async def start_proxy(host,port):
    opts = options.Options(listen_host=host,listen_port=port)
    opts.update_defer(tls_version_client_min="TLS1")
    master = DumpMaster(opts)
    addon = InterceptAddon()
    master.addons.add(addon)
    try:
        print(f"starting proxy at {host}:{port}...")
        await master.run()
    except KeyboardInterrupt:
        print("stopping proxy...")
        master.shutdown()
    finally:
        await addon.close()
        
if __name__ == "__main__":
    try:
        asyncio.run(start_proxy("0.0.0.0",8080))
    except KeyboardInterrupt:
        pass
