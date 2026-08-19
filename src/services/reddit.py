import re
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
from mitmproxy import http

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

class RedditProxy:
    def __init__(self, cookie: str = "", token: str = ""):
        self.cookie = cookie.strip() if isinstance(cookie, str) else ""
        self.token = token.strip() if isinstance(token, str) else ""

        #extract token_v2 from cookie string if not explicitly passed
        if not self.token and "token_v2" in self.cookie:
            match = re.search(r'token_v2="?([^";]+)"?', self.cookie)
            if match:
                self.token = match.group(1)

    def request(self,flow):
        host = flow.request.pretty_host
        url = flow.request.url

        #fix HTML-escaped ampersands in URLs (common in legacy Alien Blue thumbnail URLs)
        if "&amp;" in url:
            url = url.replace("&amp;", "&")
            flow.request.url = url

        parts = urlsplit(url)

        #handle Reddit mobile app config and handshake requests (v1.0 - v2.x+)
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

        #handle Reddit first-party auth token requests (v1.0 guest/login)
        if host in (REDDIT_HOSTS | {"old.reddit.com"}) and parts.path.startswith("/api/fp/"):
            print(f"[INFO] serving mocked Reddit FP auth token for: {url}")
            flow.response = http.Response.make(
                200,
                REDDIT_APP_AUTH_TOKEN_JSON,
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

        #rewrite legacy app User-Agents to modern browser User-Agent to avoid Reddit 403 blocks
        if any(app_ua in user_agent for app_ua in REDDIT_APP_USER_AGENTS):
            flow.request.headers["User-Agent"] = MODERN_USER_AGENT

        #inject configured session cookie or bearer token if present
        if self.cookie and host in (REDDIT_HOSTS | {"old.reddit.com"}):
            existing_cookie = flow.request.headers.get("Cookie","")
            if not existing_cookie:
                flow.request.headers["Cookie"] = self.cookie
            elif "reddit_session" not in existing_cookie:
                flow.request.headers["Cookie"] = f"{existing_cookie}; {self.cookie}"

        if self.token and host in (REDDIT_HOSTS | {"old.reddit.com"}):
            if "Authorization" not in flow.request.headers:
                flow.request.headers["Authorization"] = f"Bearer {self.token}"

        #route API / JSON requests to oauth.reddit.com if token is available
        if self.token and (host in REDDIT_WEB_HOSTS or host == "api.reddit.com") and self.is_api_request(flow, parts.path):
            flow.request.url = urlunsplit(("https", "oauth.reddit.com", parts.path, parts.query, parts.fragment))
            flow.request.headers["Authorization"] = f"Bearer {self.token}"
            flow.request.headers["User-Agent"] = MODERN_USER_AGENT
            return False

        if host in REDDIT_IMAGE_HOSTS or host.endswith(".redd.it") or host.endswith(".redditmedia.com"):
            flow.request.headers["User-Agent"] = MODERN_USER_AGENT
            if "Accept" not in flow.request.headers or "*/*" in flow.request.headers.get("Accept", ""):
                flow.request.headers["Accept"] = "image/jpeg,image/png,image/*;q=0.8,*/*;q=0.5"
            return False

        if host in REDDIT_API_HOSTS:
            flow.request.headers["User-Agent"] = MODERN_USER_AGENT
            return False

        if host in REDDIT_WEB_HOSTS and self.is_api_request(flow,parts.path):
            flow.request.headers["User-Agent"] = MODERN_USER_AGENT
            return False

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
                flow.response.text = flow.response.text.replace("&amp;", "&")
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
