import re
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
from mitmproxy import http

REDDIT_WEB_HOSTS = {"reddit.com","www.reddit.com"}
REDDIT_API_HOSTS = {
    "gateway.reddit.com",
    "oauth.reddit.com",
    "gql.reddit.com",
}
REDDIT_HOSTS = REDDIT_WEB_HOSTS | REDDIT_API_HOSTS

REDDIT_APP_CONFIG_JSON = b'{"experiments":{},"variables":{}}'

REDDIT_APP_USER_AGENTS = (
    "Reddit/",
    "com.reddit.Reddit",
    "RedditMobile",
    "AlienBlue",
    "Apollo",
)

REDDIT_MOBILE_CSS = f"""
<style id="legacy-proxy-mobile">
{(Path(__package__).parent/"css"/"reddit.css").read_text(encoding="utf-8")}
</style>
"""

class RedditProxy:
    def request(self,flow):
        host = flow.request.pretty_host
        url = flow.request.url
        parts = urlsplit(url)

        #handle Reddit mobile app config requests
        if host in (REDDIT_HOSTS | {"old.reddit.com"}) and parts.path.startswith("/redditmobile/"):
            print(f"[INFO] serving mocked Reddit mobile config for: {url}")
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

        if host == "old.reddit.com" and parts.path.startswith("/legacy-proxy-image/"):
            #rewrite request to point to the original image
            image_path = "/"+parts.path[len("/legacy-proxy-image/"):]
            flow.request.url = urlunsplit(
                ("https","preview.redd.it",image_path,parts.query,"")
            )
            flow.request.headers["Accept"] = "image/jpeg,image/png,image/*;q=0.8,*/*;q=0.5"
            return True

        if host in REDDIT_API_HOSTS:
            return False

        if host in REDDIT_WEB_HOSTS and self.is_api_request(flow,parts.path):
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
        content_type = flow.response.headers.get("Content-Type","")
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
