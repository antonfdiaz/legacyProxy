import re
import json
import time
import base64
import asyncio
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
from mitmproxy import http
from patchright.async_api import async_playwright

REDDIT_WEB_HOSTS = {"reddit.com","www.reddit.com"}
REDDIT_API_HOSTS = {
    "gateway.reddit.com",
    "oauth.reddit.com",
    "gql.reddit.com",
    "api.reddit.com",
}
REDDIT_IMAGE_HOSTS = {
    "preview.redd.it",
    "external-preview.redd.it",
    "i.redd.it",
    "v.redd.it",
    "b.thumbs.redditmedia.com",
    "a.thumbs.redditmedia.com",
}
REDDIT_HOSTS = REDDIT_WEB_HOSTS | REDDIT_API_HOSTS | REDDIT_IMAGE_HOSTS

REDDIT_APP_CONFIG_JSON = b'{"experiments":{},"variables":{},"status":"ok"}'
REDDIT_APP_AUTH_TOKEN_JSON = b'{"access_token":"legacy_proxy_token","token_type":"bearer","expires_in":86400,"scope":"*"}'

REDDIT_APP_USER_AGENTS = (
    "Reddit/",
    "com.reddit.Reddit",
    "RedditMobile",
    "AlienBlue",
    "Apollo",
    "iReddit",
)

MODERN_USER_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1"

REDDIT_MOBILE_CSS = f"""
<style id="legacy-proxy-mobile">
{(Path(__package__).parent/"css"/"reddit.css").read_text(encoding="utf-8")}
</style>
"""

CHROME_PATH = Path("/Applications/Google Chrome.app")
REDDIT_PROFILE_PATH = Path.home() / ".legacyProxy-reddit-profile"

def decode_jwt_exp(token: str) -> float:
    try:
        parts = token.split(".")
        if len(parts) >= 2:
            padded = parts[1]+"="*(4-len(parts[1])%4)
            payload = json.loads(base64.b64decode(padded))
            exp = payload.get("exp")
            return float(exp) if exp else 0.0
    except Exception:
        pass
    return 0.0

class RedditProxy:
    def __init__(self,cookie: str = "",token: str = "",client_id: str = "",client_secret: str = "",chrome_headless: bool = True,config = None):
        self.cookie = cookie.strip() if isinstance(cookie,str) else ""
        self.token = token.strip() if isinstance(token,str) else ""
        self.client_id = client_id.strip() if isinstance(client_id,str) else ""
        self.client_secret = client_secret.strip() if isinstance(client_secret,str) else ""
        self.chrome_headless = chrome_headless
        self.config = config

        #extract token_v2 from cookie string if not explicitly passed
        if not self.token and "token_v2" in self.cookie:
            match = re.search(r'token_v2="?([^";]+)"?',self.cookie)
            if match:
                self.token = match.group(1)

        self._access_token = self.token
        self._token_expires_at = decode_jwt_exp(self.token) if self.token else 0.0
        self._lock = asyncio.Lock()
        self._is_fetching = False

    def is_token_valid(self) -> bool:
        if not self._access_token:
            return False
        if not self._token_expires_at:
            return True
        return time.time() < self._token_expires_at-300

    async def fetch_guest_token(self) -> str:
        async with self._lock:
            if self.is_token_valid():
                return self._access_token

            print("[INFO] Auto-fetching Reddit guest token_v2 via Chrome...")
            pw = None
            context = None
            try:
                pw = await async_playwright().start()
                REDDIT_PROFILE_PATH.mkdir(parents=True,exist_ok=True)
                launch_opts = {
                    "user_data_dir": str(REDDIT_PROFILE_PATH),
                    "headless": self.chrome_headless,
                    "no_viewport": True,
                    "chromium_sandbox": True,
                    "args": [
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ]
                }
                if CHROME_PATH.exists():
                    launch_opts["channel"] = "chrome"

                context = await pw.chromium.launch_persistent_context(
                    **launch_opts,
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto("https://www.reddit.com",wait_until="networkidle",timeout=25000)
                await asyncio.sleep(2)

                cookies = await context.cookies()
                token = None
                for c in cookies:
                    if c.get("name") == "token_v2":
                        token = c.get("value")
                        break

                if token:
                    self._access_token = token
                    self._token_expires_at = decode_jwt_exp(token) or (time.time()+82800)
                    hours_left = (self._token_expires_at - time.time())/3600
                    print(f"[INFO] Successfully auto-extracted Reddit guest token_v2 (expires in {hours_left:.1f}h)")
                    if self.config:
                        self.config.services.reddit_token = token
                        from src.utils import update_config_file
                        update_config_file(self.config)
                    return token
                else:
                    print("[WARN] token_v2 cookie not found in Reddit cookies")
            except Exception as e:
                print(f"[ERROR] Failed to auto-fetch Reddit guest token: {e}")
            finally:
                if context:
                    await context.close()
                if pw:
                    await pw.stop()

            return self._access_token

    def get_token(self) -> str:
        now = time.time()
        if self._access_token and (not self.client_id or now < self._token_expires_at):
            return self._access_token

        if self.client_id and self.client_secret:
            try:
                auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
                req = urllib.request.Request(
                    "https://www.reddit.com/api/v1/access_token",
                    data=b"grant_type=client_credentials",
                    headers={
                        "Authorization": f"Basic {auth}",
                        "User-Agent": MODERN_USER_AGENT,
                        "Content-Type": "application/x-www-form-urlencoded",
                    }
                )
                resp = urllib.request.urlopen(req,timeout=10)
                data = json.loads(resp.read())
                new_token = data.get("access_token")
                if new_token:
                    self._access_token = new_token
                    expires_in = data.get("expires_in",3600)
                    self._token_expires_at = now+expires_in-60
                    print(f"[INFO] automatically fetched/refreshed Reddit OAuth token (valid for {expires_in}s)")
                    return self._access_token
            except Exception as e:
                print(f"[WARN] failed to refresh Reddit token: {e}")

        return self._access_token

    async def get_token_async(self) -> str:
        if not self.is_token_valid():
            if self.client_id and self.client_secret:
                return self.get_token()
            return await self.fetch_guest_token()
        return self.get_token()

    async def start_auto_refresh(self):
        """Background task to periodically refresh the Reddit token before expiration."""
        while True:
            try:
                if not self.is_token_valid():
                    await self.get_token_async()
            except Exception as e:
                print(f"[WARN] Background Reddit token auto-refresh error: {e}")
            await asyncio.sleep(3600)

    async def request(self,flow):
        host = flow.request.pretty_host
        url = flow.request.url

        #fix html-escaped ampersands in urls (common in legacy ab thumbnail urls)
        if "&amp;" in url:
            url = url.replace("&amp;", "&")
            flow.request.url = url

        parts = urlsplit(url)

        #handle reddit mobile app config and handshake requests (v1.0 - v2.x+)
        if host in (REDDIT_HOSTS | {"old.reddit.com"}) and (
            parts.path.startswith("/redditmobile/") or parts.path.startswith("/mobile/")
        ):
            print(f"[INFO] serving mocked Reddit mobile config/handshake for: {url}")
            flow.response = http.Response.make(
                200,
                REDDIT_APP_CONFIG_JSON,
                {
                    "Content-Type": "application/json; charset=utf-8",
                    "Cache-Control": "max-age=3600",
                    "Access-Control-Allow-Origin": "*",
                },
            )
            return True

        #handle reddit first party auth token requests (v1.0 - v1.5 guest/login)
        if host in (REDDIT_HOSTS | {"old.reddit.com"}) and parts.path.startswith("/api/fp/"):
            print(f"[INFO] serving mocked Reddit FP auth token for: {url}")
            active_token = (await self.get_token_async()) or "legacy_proxy_token"
            body = f'{{"access_token":"{active_token}","token_type":"bearer","expires_in":86400,"scope":"*"}}'.encode("utf-8")
            flow.response = http.Response.make(
                200,
                body,
                {
                    "Content-Type": "application/json; charset=utf-8",
                    "Cache-Control": "no-store",
                    "Access-Control-Allow-Origin": "*",
                },
            )
            return True

        if host == "old.reddit.com" and parts.path.startswith("/legacy-proxy-image/"):
            #rewrite request to point to the original image
            image_path = "/"+parts.path[len("/legacy-proxy-image/"):]
            flow.request.url = urlunsplit(
                ("https","preview.redd.it",image_path,parts.query,"")
            )
            flow.request.headers["Accept"] = "image/jpeg,image/png,image/*;q=0.8,*/*;q=0.5"
            return True

        user_agent = flow.request.headers.get("User-Agent","")

        #rewrite legacy app user agents to modern browser User-Agent to avoid Reddit 403 blocks
        if any(app_ua in user_agent for app_ua in REDDIT_APP_USER_AGENTS):
            flow.request.headers["User-Agent"] = MODERN_USER_AGENT

        #handle gallery URLs
        if host in REDDIT_WEB_HOSTS|{"old.reddit.com"} and parts.path.startswith("/gallery/"):
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
                return True

        #handle image hosts
        if host in REDDIT_IMAGE_HOSTS or host.endswith(".redd.it") or host.endswith(".redditmedia.com"):
            flow.request.headers["User-Agent"] = MODERN_USER_AGENT
            if "Accept" not in flow.request.headers or "*/*" in flow.request.headers.get("Accept", ""):
                flow.request.headers["Accept"] = "image/jpeg,image/png,image/*;q=0.8,*/*;q=0.5"
            return False

        #check if this is an api/data request (e.g. alien blue, reddit app, json endpoints)
        is_api = host in REDDIT_API_HOSTS or ((host in REDDIT_WEB_HOSTS or host == "api.reddit.com") and self.is_api_request(flow, parts.path))
        if is_api:
            active_token = await self.get_token_async()
            if self.cookie:
                existing_cookie = flow.request.headers.get("Cookie","")
                if not existing_cookie:
                    flow.request.headers["Cookie"] = self.cookie
                elif "reddit_session" not in existing_cookie:
                    flow.request.headers["Cookie"] = f"{existing_cookie}; {self.cookie}"

            if active_token:
                if host in REDDIT_WEB_HOSTS or host == "api.reddit.com":
                    flow.request.url = urlunsplit(("https","oauth.reddit.com",parts.path,parts.query,parts.fragment))
                flow.request.headers["Authorization"] = f"Bearer {active_token}"

            flow.request.headers["User-Agent"] = MODERN_USER_AGENT
            return False

        #standard web browser navigation on reddit.com/www.reddit.com -> redirect to old.reddit.com
        if host in REDDIT_WEB_HOSTS:
            print(f"intercepting Reddit request: {url}")
            redirect_url = urlunsplit(
                (parts.scheme,"old.reddit.com",parts.path,parts.query,parts.fragment)
            )
            flow.response = http.Response.make(
                302,
                b"",
                {"Location": redirect_url,"Cache-Control": "no-store"},
            )
            return True

        return False

    def is_api_request(self,flow,path):
        accept = flow.request.headers.get("Accept","").lower()
        user_agent = flow.request.headers.get("User-Agent","")
        return (
            flow.request.method not in {"GET","HEAD"}
            or path.startswith("/api/")
            or path.startswith("/redditmobile/")
            or path.startswith("/mobile/")
            or path.startswith("/svc/")
            or path.startswith("/graphql")
            or path.endswith(".json")
            or path.endswith(".xml")
            or "application/json" in accept
            or "application/x-protobuf" in accept
            or "Authorization" in flow.request.headers
            or "X-Reddit-Session" in flow.request.headers
            or any(app_ua in user_agent for app_ua in REDDIT_APP_USER_AGENTS)
        )

    def response(self,flow):
        content_type = flow.response.headers.get("Content-Type","").lower()
        if "application/json" in content_type:
            if "&amp;" in flow.response.text:
                flow.response.text = flow.response.text.replace("&amp;","&")
                return True
            return False

        if flow.request.pretty_host != "old.reddit.com" or "text/html" not in content_type:
            return False

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
        html = html.replace("</head>",REDDIT_MOBILE_CSS+"</head>",1) #inject custom css
        flow.response.text = html
        return True
