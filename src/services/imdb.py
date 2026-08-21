import asyncio
import datetime
import hashlib
import hmac
import json
import ssl
import time
import urllib.parse
import urllib.request
from mitmproxy import http

IMDB_APP_KEY = "c2a5f61b-8dea-44bc-b739-db7937519f4e"
CREDENTIALS_URL = "https://api.imdbws.com/authentication/credentials/temporary/android860"

IMDB_API_HOSTS = {
    "api.imdbws.com",
    "app.imdb.com",
}

IMDB_CONFIG_HOSTS = {
    "ios-app-config.media-imdb.com",
}

IMDB_AD_HOSTS = {
    "mads.amazon-adsystem.com",
    "aax-us-east.amazon-adsystem.com",
    "aax.amazon-adsystem.com",
}

IMDB_TELEMETRY_HOSTS = {
    "fls-na.amazon.com",
    "unagi.amazon.com",
    "unagi-na.amazon.com",
    "udm.scorecardresearch.com",
    "b.scorecardresearch.com",
}

IMDB_ALL_HOSTS = IMDB_API_HOSTS | IMDB_CONFIG_HOSTS | IMDB_AD_HOSTS | IMDB_TELEMETRY_HOSTS | {
    "imdb.com",
    "www.imdb.com",
    "m.imdb.com",
    "ia.media-imdb.com",
    "m.media-amazon.com",
    "v2.sg.media-imdb.com",
}


class IMDbProxy:
    def __init__(self, config=None):
        self.config = config
        self._access_key_id = ""
        self._secret_access_key = ""
        self._session_token = ""
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    def is_token_valid(self) -> bool:
        if not (self._access_key_id and self._secret_access_key and self._session_token):
            return False
        return time.time() < (self._expires_at - 300)

    async def fetch_credentials(self) -> bool:
        async with self._lock:
            if self.is_token_valid():
                return True
            try:
                print("[INFO] Fetching IMDb temporary AWS credentials...")
                data = json.dumps({"appKey": IMDB_APP_KEY}).encode("utf-8")
                req = urllib.request.Request(
                    CREDENTIALS_URL,
                    data=data,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "IMDb_Android/8.6.0",
                    },
                )
                ctx = ssl._create_unverified_context()
                loop = asyncio.get_running_loop()

                def _do_fetch():
                    with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                        return json.loads(resp.read().decode("utf-8"))

                resp_data = await loop.run_in_executor(None, _do_fetch)
                resource = resp_data.get("resource", {})
                self._access_key_id = resource.get("accessKeyId", "")
                self._secret_access_key = resource.get("secretAccessKey", "")
                self._session_token = resource.get("sessionToken", "")

                exp_str = resource.get("expirationTimeStamp", "")
                if exp_str:
                    try:
                        exp_dt = datetime.datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                        self._expires_at = exp_dt.timestamp()
                    except Exception:
                        self._expires_at = time.time() + 86400
                else:
                    self._expires_at = time.time() + 86400

                hours_left = (self._expires_at - time.time()) / 3600
                print(f"[INFO] Successfully retrieved IMDb AWS credentials (valid for {hours_left:.1f}h)")
                return True
            except Exception as e:
                print(f"[ERROR] Failed to fetch IMDb temporary credentials: {e}")
                return False

    async def get_credentials_async(self):
        if not self.is_token_valid():
            await self.fetch_credentials()
        return self._access_key_id, self._secret_access_key, self._session_token

    async def start_auto_refresh(self):
        """Background task to periodically refresh IMDb credentials."""
        while True:
            try:
                if not self.is_token_valid():
                    await self.fetch_credentials()
            except Exception as e:
                print(f"[WARN] Background IMDb credentials refresh error: {e}")
            await asyncio.sleep(3600)

    def sign_sigv4(self, method: str, url: str, body: bytes = b"") -> dict:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or "api.imdbws.com"
        path = parsed.path or "/"
        query = parsed.query

        t = datetime.datetime.now(datetime.timezone.utc)
        amz_date = t.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = t.strftime("%Y%m%d")
        region = "us-east-1"
        service = "imdbapi"

        canonical_uri = path
        if query:
            # AWS SigV4 requires RFC 3986 encoding (spaces as %20, safe='-_.~')
            params = urllib.parse.parse_qsl(query, keep_blank_values=True)
            encoded_params = [
                (urllib.parse.quote(k, safe="-_.~"), urllib.parse.quote(v, safe="-_.~"))
                for k, v in params
            ]
            encoded_params.sort(key=lambda p: (p[0], p[1]))
            canonical_querystring = "&".join(f"{k}={v}" for k, v in encoded_params)
        else:
            canonical_querystring = ""

        canonical_headers = f"host:{host}\nx-amz-date:{amz_date}\nx-amz-security-token:{self._session_token}\n"
        signed_headers = "host;x-amz-date;x-amz-security-token"
        payload_hash = hashlib.sha256(body).hexdigest()
        canonical_request = f"{method.upper()}\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"

        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
        string_to_sign = f"{algorithm}\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"

        def _hmac(key, msg):
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        k_date = _hmac(("AWS4" + self._secret_access_key).encode("utf-8"), date_stamp)
        k_region = _hmac(k_date, region)
        k_service = _hmac(k_region, service)
        k_signing = _hmac(k_service, "aws4_request")
        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        auth_header = f"{algorithm} Credential={self._access_key_id}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"
        return {
            "Host": host,
            "x-amz-date": amz_date,
            "x-amz-security-token": self._session_token,
            "Authorization": auth_header,
            "User-Agent": "IMDb_Android/8.6.0",
        }

    async def _get_cleaned_config(self, url: str) -> bytes:
        """Fetch and clean iphone.json.gz to remove dead ad/editorial widgets."""
        loop = asyncio.get_running_loop()
        def _fetch_and_clean():
            ctx = ssl._create_unverified_context()
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                raw = resp.read()
                if raw[:2] == b"\x1f\x8b":
                    import gzip
                    data = json.loads(gzip.decompress(raw))
                else:
                    data = json.loads(raw)

            dead_classes = {
                "IMNativeAdArticlePhoneWidget",
                "IMDb.ContentSymphonyWidget",
                "IMAwardResultsWidget",
            }
            dead_names = {"old", "polls", "natvad"}

            def clean_sections(sections):
                new_sections = []
                for s in sections:
                    new_items = []
                    for it in s.get("items", []):
                        if it.get("class") in dead_classes or it.get("name") in dead_names:
                            continue
                        new_items.append(it)
                    if new_items:
                        s["items"] = new_items
                        new_sections.append(s)
                return new_sections

            if "data" in data:
                for page_key in [
                    "home_page",
                    "movies_home_page",
                    "tv_home_page",
                    "celeb_home_page",
                    "watch_today_home_page",
                    "trending_home_page",
                    "best_and_worst_home_page",
                ]:
                    if page_key in data["data"] and isinstance(data["data"][page_key], dict):
                        page = data["data"][page_key]
                        page["sections"] = clean_sections(page.get("sections", []))

            return json.dumps(data).encode("utf-8")

        try:
            return await loop.run_in_executor(None, _fetch_and_clean)
        except Exception as e:
            print(f"[WARN] Failed to clean iphone.json.gz: {e}")
            return b""

    async def request(self, flow) -> bool:
        host = flow.request.pretty_host.lower()
        path = flow.request.path.split("?", 1)[0]

        # 1. Handle app config (clean dead widgets from iphone.json.gz)
        if host in IMDB_CONFIG_HOSTS and path.endswith("iphone.json.gz"):
            cleaned_data = await self._get_cleaned_config(flow.request.url)
            if cleaned_data:
                flow.response = http.Response.make(
                    200,
                    cleaned_data,
                    {
                        "Content-Type": "application/json; charset=utf-8",
                        "Content-Length": str(len(cleaned_data)),
                        "Cache-Control": "public, max-age=86400",
                    },
                )
                return True

        # 2. Handle ad hosts
        if host in IMDB_AD_HOSTS or host.endswith(".amazon-adsystem.com"):
            flow.response = http.Response.make(
                200,
                b"{}",
                {
                    "Content-Type": "application/json; charset=utf-8",
                    "Cache-Control": "public, max-age=86400",
                },
            )
            return True

        # 3. Handle telemetry / analytics hosts
        if host in IMDB_TELEMETRY_HOSTS or host.endswith(".scorecardresearch.com"):
            flow.response = http.Response.make(
                200,
                b"",
                {
                    "Content-Type": "text/plain; charset=utf-8",
                    "Cache-Control": "no-store",
                },
            )
            return True

        # 4. Handle IMDb API telemetry & ad endpoints
        if host in IMDB_API_HOSTS:
            if path.startswith("/metrics/"):
                flow.response = http.Response.make(
                    200,
                    b'{"status":"ok"}',
                    {
                        "Content-Type": "application/json; charset=utf-8",
                        "Cache-Control": "no-store",
                    },
                )
                return True

            if "ad-config-v2.jstl" in path or "ad-config" in path:
                flow.response = http.Response.make(
                    200,
                    b'{"adPlacements":[]}',
                    {
                        "Content-Type": "application/json; charset=utf-8",
                        "Cache-Control": "public, max-age=86400",
                    },
                )
                return True

            # Handle news fallback endpoints
            if path.startswith("/news/"):
                flow.response = http.Response.make(
                    200,
                    b'{"resource":{"@type":"imdb.api.news","items":[]}}',
                    {
                        "Content-Type": "application/json; charset=utf-8",
                        "Cache-Control": "public, max-age=3600",
                    },
                )
                return True

            # Template URL rewriting & bug fixes
            if "name-auxiliary-v7.jstl" in flow.request.url:
                flow.request.url = flow.request.url.replace("name-auxiliary-v7.jstl", "name-auxiliary-v6.jstl")

            # Route photo galleries
            if "photo-galleries" in flow.request.url or "featured-photos" in flow.request.url or "featured-galleries" in flow.request.url:
                flow.request.url = "https://api.imdbws.com/template/imdb-ios-writable/featured-galleries-v1.jstl/render"

            # Route Top 250
            if "chart-top250" in flow.request.url or "chart-top-250-tv" in flow.request.url:
                flow.request.url = "https://api.imdbws.com/template/imdb-ios-writable/chart-top-250-v1.jstl/render"

            # Route Bottom 100
            if "chart-bottom100" in flow.request.url:
                flow.request.url = "https://api.imdbws.com/template/imdb-ios-writable/chart-bottom-100-v1.jstl/render"

            # Route Coming Soon
            if "coming-soon" in flow.request.url or "comingsoon" in flow.request.url:
                flow.request.url = "https://api.imdbws.com/template/imdb-ios-writable/chart-top-250-v1.jstl/render"

            # Route Box Office
            if "boxoffice" in flow.request.url or "box-office" in flow.request.url:
                flow.request.url = "https://api.imdbws.com/template/imdb-ios-writable/chart-moviemeter-v2.jstl/render"

            # Strip legacy client AWS and authorization headers to avoid conflicts
            for header_name in list(flow.request.headers.keys()):
                if header_name.lower().startswith(("x-amz", "authorization")):
                    del flow.request.headers[header_name]

            # Sign request with AWS SigV4
            await self.get_credentials_async()
            if self.is_token_valid():
                body = flow.request.raw_content or b""
                sig_headers = self.sign_sigv4(flow.request.method, flow.request.url, body)
                for k, v in sig_headers.items():
                    flow.request.headers[k] = v
                return False

        # 5. Handle web app content fallback (e.g. m.imdb.com/app/content/homepage)
        if host in {"m.imdb.com", "www.imdb.com"} and path.startswith("/app/content/"):
            flow.response = http.Response.make(
                200,
                b"{}",
                {
                    "Content-Type": "application/json; charset=utf-8",
                    "Cache-Control": "no-store",
                },
            )
            return True

        return False

    def response(self, flow):
        host = flow.request.pretty_host.lower()
        if host in IMDB_API_HOSTS:
            if flow.response.status_code == 403:
                body = flow.response.text.lower()
                if "expired" in body or "security token" in body:
                    print("[WARN] IMDb API security token expired. Invalidating cached credentials...")
                    self._access_key_id = ""
                    self._secret_access_key = ""
                    self._session_token = ""
                    self._expires_at = 0.0
                else:
                    print(f"[WARN] IMDb API 403 for {flow.request.url}: {flow.response.text[:200]}")
            elif flow.response.status_code >= 400:
                print(f"[WARN] IMDb API {flow.request.url} returned {flow.response.status_code}: {flow.response.text[:200]}")