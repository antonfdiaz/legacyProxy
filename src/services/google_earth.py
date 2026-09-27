from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

GOOGLE_EARTH_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.6.1 Safari/605.1.15"
)

GOOGLE_EARTH_HOSTS = {
    "kh.google.com",
    "keyhole.com",
}

def is_google_earth_host(host: str) -> bool:
    if not host:
        return False
    host = host.lower().rstrip(".")
    if host in GOOGLE_EARTH_HOSTS:
        return True
    if host.endswith(".kh.google.com") or host.endswith(".keyhole.com"):
        return True
    if host.startswith("khm") and host.endswith(".google.com"):
        return True
    return False

def is_google_earth_request(flow) -> bool:
    request = getattr(flow, "request", None)
    if not request:
        return False

    host = (getattr(request, "pretty_host", "") or "").lower().rstrip(".")
    user_agent = request.headers.get("User-Agent", "")

    if "googleearth" in user_agent.lower() or "google earth" in user_agent.lower():
        return True

    return is_google_earth_host(host)

class GoogleEarthProxy:
    """
    Proxy service to fix Google Earth on legacy iOS devices without requiring the OpenEarthX tweak.
    
    Replicates and improves upon OpenEarthX (https://github.com/Epixx512/OpenEarthX):
    1. Replaces outdated iOS Google Earth User-Agent with modern Safari User-Agent
       to bypass Google servers returning 403 Forbidden.
    2. Strips the 'type=embedded' query parameter from /dbRoot.v5 requests,
       which otherwise causes Google servers to return 404 Not Found.
    """
    def __init__(self, user_agent: str = GOOGLE_EARTH_USER_AGENT):
        self.user_agent = user_agent

    def strip_embedded_param(self, url: str) -> str:
        parts = urlsplit(url)
        if "type=embedded" in parts.query:
            query_pairs = parse_qsl(parts.query, keep_blank_values=True)
            filtered = [(k, v) for k, v in query_pairs if not (k == "type" and v == "embedded")]
            new_query = urlencode(filtered)
            return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))
        return url

    def request(self, flow) -> bool:
        if not is_google_earth_request(flow):
            return False

        # 1. User-Agent spoofing
        user_agent = flow.request.headers.get("User-Agent", "")
        if user_agent != self.user_agent:
            flow.request.headers["User-Agent"] = self.user_agent

        # 2. Fix dbRoot requests
        path = flow.request.path.split("?", 1)[0].lower()
        if "dbroot" in path:
            original_url = flow.request.url
            new_url = self.strip_embedded_param(original_url)
            if new_url != original_url:
                print(f"[INFO] Google Earth: stripped type=embedded from {original_url}")
                flow.request.url = new_url

        print(f"[INFO] Google Earth: processed request {flow.request.url}")
        return True
