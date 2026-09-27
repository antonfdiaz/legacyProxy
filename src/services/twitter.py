import asyncio
import datetime
import json
import logging
import platform
import re
import time
import requests
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from mitmproxy import http
from patchright.async_api import async_playwright

logger = logging.getLogger("legacyProxy.twitter")

TWITTER_API_HOSTS = {
    "api.twitter.com",
    "mobile.twitter.com",
    "upload.twitter.com",
    "cards.twitter.com",
    "twimg.com",
    "abs.twimg.com",
    "pbs.twimg.com",
}

TWITTER_MEDIA_HOSTS = {"twimg.com", "abs.twimg.com", "pbs.twimg.com"}

CRASHLYTICS_HOSTS = {
    "settings.crashlytics.com",
    "crashlytics.com",
}

TWITTER_BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

GRAPHQL_QUERY_IDS = {
    "HomeTimeline": "c-CzHF1LboFilMpsx4ZCrQ",
    "HomeLatestTimeline": "BKB7oi212Fi7kQtCBGE4zA",
    "UserByScreenName": "1VOOyvKkiI3FMmkeDNxM9A",
    "UserTweets": "q6xj5bs0hapm9309hexA_g",
    "TweetDetail": "xd_EMdYvB9hfZsZ6Idri0w",
    "Likes": "lIDpu_NWL7_VhimGGt0o6A",
    "SearchTimeline": "VhUd6vHVmLBcw0uX-6jMLA",
    "Followers": "IOh4aS6UdGWGJUYTqliQ7Q",
    "Following": "zx6e-TLzRkeDO_a7p4b3JQ",
}

GRAPHQL_FEATURES = {
    "responsive_web_graphql_exclude_directive_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "tweetypie_unmention_optimization_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "responsive_web_media_download_video_enabled": True,
    "freedom_of_speech_not_reach_fetch_enabled": True,
}

if platform.system() == "Darwin":
    CHROME_PATH = Path("/Applications/Google Chrome.app")
elif platform.system() == "Linux":
    CHROME_PATH = Path("/usr/bin/google-chrome")
else:
    CHROME_PATH = Path()

TWITTER_PROFILE_PATH = Path.home() / ".legacyProxy-twitter-profile"

DEFAULT_USER = {
    "id": 123456789,
    "id_str": "123456789",
    "name": "iOS 7 User",
    "screen_name": "legacy_user",
    "location": "Cupertino, CA",
    "description": "Tweeting from iOS 7.1.2 via legacyProxy 🚀",
    "url": None,
    "entities": {"description": {"urls": []}},
    "protected": False,
    "followers_count": 42,
    "friends_count": 10,
    "listed_count": 1,
    "created_at": "Wed May 23 06:01:13 +0000 2012",
    "favourites_count": 7,
    "utc_offset": None,
    "time_zone": None,
    "geo_enabled": False,
    "verified": True,
    "statuses_count": 1,
    "lang": "es",
    "profile_background_color": "C0DEED",
    "profile_background_image_url": "http://abs.twimg.com/images/themes/theme1/bg.png",
    "profile_background_image_url_https": "https://abs.twimg.com/images/themes/theme1/bg.png",
    "profile_background_tile": False,
    "profile_image_url": "http://abs.twimg.com/sticky/default_profile_images/default_profile_normal.png",
    "profile_image_url_https": "https://abs.twimg.com/sticky/default_profile_images/default_profile_normal.png",
    "profile_link_color": "0084B4",
    "profile_sidebar_border_color": "C0DEED",
    "profile_sidebar_fill_color": "DDEEF6",
    "profile_text_color": "333333",
    "profile_use_background_image": True,
    "default_profile": True,
    "default_profile_image": True,
    "following": False,
    "follow_request_sent": False,
    "notifications": False,
}

TWITTER_CONFIG = {
    "characters_reserved_per_media": 24,
    "max_media_per_upload": 4,
    "non_username_paths": ["about", "help"],
    "photo_size_limit": 3145728,
    "photo_sizes": {
        "thumb": {"w": 150, "h": 150, "resize": "crop"},
        "small": {"w": 340, "h": 480, "resize": "fit"},
        "medium": {"w": 600, "h": 1200, "resize": "fit"},
        "large": {"w": 1024, "h": 2048, "resize": "fit"},
    },
    "short_url_length": 23,
    "short_url_length_https": 23,
}


def is_twitter_request(flow: http.HTTPFlow) -> bool:
    request = getattr(flow, "request", None)
    if not request:
        return False

    host = (getattr(request, "pretty_host", "") or "").lower().rstrip(".")
    # Image and static asset requests must go upstream unchanged. Treating them
    # as API calls makes the fallback below return JSON in place of the image.
    if any(host == h or host.endswith("." + h) for h in TWITTER_MEDIA_HOSTS):
        return False
    if host in TWITTER_API_HOSTS or host in CRASHLYTICS_HOSTS:
        return True
    if any(host.endswith("." + h) for h in TWITTER_API_HOSTS | CRASHLYTICS_HOSTS):
        return True

    user_agent = request.headers.get("User-Agent", "")
    if "Twitter/" in user_agent or "Tweetie" in user_agent or "com.atebits.Tweetie2" in user_agent:
        return True

    return False


def graphql_tweet_to_v1(tweet_result: Any) -> Optional[Dict[str, Any]]:
    """Convert modern Twitter GraphQL tweet results to legacy v1.1 status dictionary."""
    if not tweet_result or not isinstance(tweet_result, dict):
        return None

    if tweet_result.get("__typename") == "TweetWithVisibilityResults":
        tweet_result = tweet_result.get("tweet", {})

    legacy = tweet_result.get("legacy")
    if not legacy or not isinstance(legacy, dict):
        return None

    rest_id = tweet_result.get("rest_id", "0")
    user_result = tweet_result.get("core", {}).get("user_results", {}).get("result", {})
    user_legacy = user_result.get("legacy", {})
    user_id = user_result.get("rest_id", "0")

    avatar_url = user_legacy.get(
        "profile_image_url_https",
        "http://abs.twimg.com/sticky/default_profile_images/default_profile_normal.png",
    )
    # Ensure HTTP version is available for iOS 7 if needed
    avatar_http = avatar_url.replace("https://", "http://")

    user = {
        "id": int(user_id) if user_id.isdigit() else 0,
        "id_str": str(user_id),
        "name": user_legacy.get("name", "Twitter User"),
        "screen_name": user_legacy.get("screen_name", "user"),
        "location": user_legacy.get("location", ""),
        "description": user_legacy.get("description", ""),
        "url": user_legacy.get("url", None),
        "entities": user_legacy.get("entities", {"description": {"urls": []}}),
        "protected": user_legacy.get("protected", False),
        "followers_count": user_legacy.get("followers_count", 0),
        "friends_count": user_legacy.get("friends_count", 0),
        "listed_count": user_legacy.get("listed_count", 0),
        "created_at": user_legacy.get("created_at", "Wed May 23 06:01:13 +0000 2012"),
        "favourites_count": user_legacy.get("favourites_count", 0),
        "utc_offset": None,
        "time_zone": None,
        "geo_enabled": user_legacy.get("geo_enabled", False),
        "verified": user_legacy.get("verified", False) or user_result.get("is_blue_verified", False),
        "statuses_count": user_legacy.get("statuses_count", 0),
        "lang": user_legacy.get("lang", "en"),
        "profile_image_url": avatar_http,
        "profile_image_url_https": avatar_url,
        "profile_banner_url": user_legacy.get("profile_banner_url"),
        "profile_background_image_url": "http://abs.twimg.com/images/themes/theme1/bg.png",
        "profile_background_image_url_https": "https://abs.twimg.com/images/themes/theme1/bg.png",
        "profile_link_color": "0084B4",
        "default_profile": False,
        "default_profile_image": False,
        "following": user_legacy.get("following", False),
        "follow_request_sent": False,
        "notifications": False,
    }

    v1_tweet = dict(legacy)
    v1_tweet["id"] = int(rest_id) if rest_id.isdigit() else 0
    v1_tweet["id_str"] = str(rest_id)
    v1_tweet["text"] = legacy.get("full_text", legacy.get("text", ""))
    v1_tweet["source"] = '<a href="http://twitter.com">Twitter for Web</a>'
    v1_tweet["truncated"] = False
    v1_tweet["user"] = user

    # Map retweet if present
    retweet_result = legacy.get("retweeted_status_result", {}).get("result")
    if retweet_result:
        v1_retweet = graphql_tweet_to_v1(retweet_result)
        if v1_retweet:
            v1_tweet["retweeted_status"] = v1_retweet

    return v1_tweet


def extract_tweets_from_graphql(data: Any) -> List[Dict[str, Any]]:
    """Recursively traverse arbitrary GraphQL response dictionaries and collect valid v1 tweets."""
    tweets = []
    seen_ids = set()

    def walk(obj: Any):
        if isinstance(obj, dict):
            if "tweet_results" in obj and isinstance(obj["tweet_results"], dict):
                res = obj["tweet_results"].get("result")
                v1 = graphql_tweet_to_v1(res)
                if v1 and v1.get("id_str") not in seen_ids:
                    seen_ids.add(v1["id_str"])
                    tweets.append(v1)
            elif obj.get("__typename") in ("Tweet", "TweetWithVisibilityResults") and "legacy" in obj:
                v1 = graphql_tweet_to_v1(obj)
                if v1 and v1.get("id_str") not in seen_ids:
                    seen_ids.add(v1["id_str"])
                    tweets.append(v1)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    return tweets


def graphql_user_to_v1(user_result: Any) -> Optional[Dict[str, Any]]:
    """Convert a modern GraphQL user result to a legacy v1.1 user object."""
    if not isinstance(user_result, dict):
        return None
    if user_result.get("__typename") in {"UserWithVisibilityResults", "UserWithSafetyMode"}:
        user_result = user_result.get("user", {})
    legacy = user_result.get("legacy")
    if not isinstance(legacy, dict):
        return None
    user_id = str(user_result.get("rest_id") or legacy.get("id_str") or "0")
    avatar = legacy.get("profile_image_url_https", "")
    user = dict(legacy)
    user["id_str"] = user_id
    user["id"] = int(user_id) if user_id.isdigit() else 0
    user["profile_image_url"] = avatar.replace("https://", "http://")
    user["profile_image_url_https"] = avatar
    return user


def extract_users_from_graphql(data: Any) -> List[Dict[str, Any]]:
    """Collect unique legacy users from arbitrary GraphQL response data."""
    users: List[Dict[str, Any]] = []
    seen_ids = set()

    def walk(obj: Any):
        if isinstance(obj, dict):
            candidates = []
            for key in ("user_results", "user", "viewer", "viewer_v2", "user_by_rest_id"):
                value = obj.get(key)
                if isinstance(value, dict):
                    candidates.append(value.get("result", value))
            for result in candidates:
                user = graphql_user_to_v1(result)
                if user and user["id_str"] not in seen_ids:
                    seen_ids.add(user["id_str"])
                    users.append(user)
            if obj.get("__typename", "").startswith("User"):
                user = graphql_user_to_v1(obj)
                if user and user["id_str"] not in seen_ids:
                    seen_ids.add(user["id_str"])
                    users.append(user)
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(data)
    return users


def extract_viewer_id_from_graphql(data: Any) -> Optional[str]:
    """Find the authenticated user's id when a GraphQL response exposes it."""
    if isinstance(data, dict):
        session = data.get("session")
        if isinstance(session, dict) and session.get("user_id"):
            return str(session["user_id"])
        for key in ("viewer", "viewer_v2"):
            value = data.get(key)
            if isinstance(value, dict):
                result = value.get("result", value)
                if isinstance(result, dict) and result.get("rest_id"):
                    return str(result["rest_id"])
                nested = value.get("user_results")
                if isinstance(nested, dict):
                    result = nested.get("result")
                    if isinstance(result, dict) and result.get("rest_id"):
                        return str(result["rest_id"])
        for value in data.values():
            found = extract_viewer_id_from_graphql(value)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = extract_viewer_id_from_graphql(value)
            if found:
                return found
    return None


class TwitterProxy:
    """
    Proxy service to revitalize Twitter 5.x for legacy iOS devices using real Twitter/X data.
    
    Supports:
    1. Direct credential configuration (auth_token & ct0 in config.json)
    2. A persistent HTTP session for Twitter GraphQL with browser fallback only
       when no cookies are configured
    3. Real-time translation of Twitter GraphQL responses into v1.1 status format
    4. Crashlytics telemetry suppression
    5. Decider SPDY-disable to enforce HTTP proxy compatibility
    6. xAuth OAuth 1.0a handshake emulation
    """

    def __init__(self, config=None, auth_token: str = "", ct0: str = ""):
        self.config = config
        
        # Load credentials from arguments or config
        cfg_services = getattr(config, "services", None) if config else None
        self.auth_token = auth_token or getattr(cfg_services, "twitter_auth_token", "")
        self.ct0 = ct0 or getattr(cfg_services, "twitter_ct0", "")
        self.bearer_token = getattr(cfg_services, "twitter_bearer_token", "") or unquote(TWITTER_BEARER_TOKEN)
        if self.bearer_token.lower().startswith("bearer "):
            self.bearer_token = self.bearer_token[7:].strip()
        
        cfg_general = getattr(config, "general", None) if config else None
        self.chrome_headless = getattr(cfg_general, "chrome_headless", False)

        self.logged_in_user = dict(DEFAULT_USER)
        self.posted_tweets: List[Dict[str, Any]] = []

        self._cached_timeline: List[Dict[str, Any]] = []
        self._cache_time: float = 0.0
        self._cached_users: Dict[str, Dict[str, Any]] = {}
        self._cached_user_tweets: Dict[str, List[Dict[str, Any]]] = {}
        self._browser_cache: Dict[str, Tuple[float, List[Dict[str, Any]], List[Dict[str, Any]]]] = {}
        self._lock = asyncio.Lock()
        self._browser_fetch_lock = asyncio.Lock()
        self._direct_http_lock = asyncio.Lock()
        self._http_session = requests.Session()
        self._query_ids = dict(GRAPHQL_QUERY_IDS)
        self._query_ids_refreshed = False
        self._viewer_id: Optional[str] = None
        self._is_browser_running = False

    def _json_response(self, data: Any, status_code: int = 200) -> http.Response:
        content = json.dumps(data, ensure_ascii=False).encode("utf-8")
        return http.Response.make(
            status_code,
            content,
            {
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-cache",
                "Access-Control-Allow-Origin": "*",
            },
        )

    def _text_response(self, text: str, status_code: int = 200) -> http.Response:
        return http.Response.make(
            status_code,
            text.encode("utf-8"),
            {
                "Content-Type": "text/plain; charset=utf-8",
                "Cache-Control": "no-cache",
            },
        )

    def _format_twitter_date(self, dt: Optional[datetime.datetime] = None) -> str:
        if dt is None:
            dt = datetime.datetime.now(datetime.timezone.utc)
        return dt.strftime("%a %b %d %H:%M:%S +0000 %Y")

    def _direct_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.bearer_token}",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://x.com",
            "Referer": "https://x.com/",
            "x-twitter-active-user": "yes",
            "x-twitter-auth-type": "OAuth2Session",
            "x-csrf-token": self.ct0,
        }

    def _refresh_query_ids_sync(self) -> None:
        """Refresh operation IDs from the web client without starting a browser."""
        if not self.auth_token:
            return
        self._query_ids_refreshed = True
        self._http_session.cookies.set("auth_token", self.auth_token, domain=".x.com")
        if self.ct0:
            self._http_session.cookies.set("ct0", self.ct0, domain=".x.com")
        try:
            response = self._http_session.get(
                "https://x.com/home", headers=self._direct_headers(), timeout=12
            )
            response.raise_for_status()
            html = response.text
            script_matches = re.finditer(
                r"(?:src|href)=['\"](https://abs\.twimg\.com/responsive-web/client-web[^'\"]+\.js)['\"]",
                html,
            )
            script_urls = list(dict.fromkeys(match.group(1) for match in script_matches))[:12]
            for script_url in script_urls:
                try:
                    bundle = self._http_session.get(
                        script_url, headers=self._direct_headers(), timeout=12
                    ).text
                except requests.RequestException:
                    continue
                for operation in re.finditer(
                    r"queryId:\s*['\"]([A-Za-z0-9_-]+)['\"][^}]{0,240}?operationName:\s*['\"]([^'\"]+)['\"]",
                    bundle,
                ):
                    self._query_ids[operation.group(2)] = operation.group(1)
                for operation in re.finditer(
                    r"operationName:\s*['\"]([^'\"]+)['\"][^}]{0,240}?queryId:\s*['\"]([A-Za-z0-9_-]+)['\"]",
                    bundle,
                ):
                    self._query_ids[operation.group(1)] = operation.group(2)
            logger.info("[Twitter] Direct API session ready (%d GraphQL operations)", len(self._query_ids))
        except requests.RequestException as exc:
            logger.warning("[Twitter] Direct API session could not load x.com: %s", exc)

    def _direct_graphql_sync(
        self, operation: str, variables: Dict[str, Any], retry: bool = True
    ) -> Optional[Dict[str, Any]]:
        if not self.auth_token:
            return None
        if not self._query_ids_refreshed:
            self._refresh_query_ids_sync()
        query_id = self._query_ids.get(operation)
        if not query_id:
            return None
        self._http_session.cookies.set("auth_token", self.auth_token, domain=".x.com")
        if self.ct0:
            self._http_session.cookies.set("ct0", self.ct0, domain=".x.com")
        url = f"https://x.com/i/api/graphql/{query_id}/{operation}"
        payload = {"variables": variables, "features": GRAPHQL_FEATURES, "queryId": query_id}
        if operation == "SearchTimeline":
            url += "?" + urlencode(
                {
                    "variables": json.dumps(variables, separators=(",", ":")),
                    "features": json.dumps(GRAPHQL_FEATURES, separators=(",", ":")),
                }
            )
            payload = {"features": GRAPHQL_FEATURES, "queryId": query_id}
        try:
            response = self._http_session.post(
                url, headers=self._direct_headers(), json=payload, timeout=20
            )
            if response.status_code == 404 and retry:
                self._query_ids_refreshed = False
                return self._direct_graphql_sync(operation, variables, retry=False)
            if response.status_code >= 400:
                logger.warning("[Twitter] Direct GraphQL %s returned HTTP %s", operation, response.status_code)
                return None
            data = response.json()
            return data if isinstance(data, dict) else None
        except (requests.RequestException, ValueError) as exc:
            logger.warning("[Twitter] Direct GraphQL %s failed: %s", operation, exc)
            return None

    async def _direct_graphql(
        self, operation: str, variables: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        async with self._direct_http_lock:
            return await asyncio.to_thread(self._direct_graphql_sync, operation, variables)

    async def _direct_verify_credentials(self) -> bool:
        if not self.auth_token:
            return False

        def fetch() -> Optional[Dict[str, Any]]:
            self._http_session.cookies.set("auth_token", self.auth_token, domain=".twitter.com")
            if self.ct0:
                self._http_session.cookies.set("ct0", self.ct0, domain=".twitter.com")
            try:
                response = self._http_session.get(
                    "https://api.twitter.com/1.1/account/verify_credentials.json",
                    headers=self._direct_headers(), timeout=12,
                )
                if response.status_code == 200:
                    value = response.json()
                    return value if isinstance(value, dict) else None
            except (requests.RequestException, ValueError):
                pass
            return None

        async with self._direct_http_lock:
            user = await asyncio.to_thread(fetch)
        if user and user.get("id_str"):
            self.logged_in_user = user
            self._viewer_id = str(user["id_str"])
            self._cached_users[self._viewer_id] = user
            if user.get("screen_name"):
                self._cached_users[user["screen_name"].lower()] = user
            return True
        return False

    def _remember_graphql(self, data: Any) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        tweets = extract_tweets_from_graphql(data)
        users = extract_users_from_graphql(data)
        viewer_id = extract_viewer_id_from_graphql(data)
        if viewer_id:
            self._viewer_id = viewer_id
        for user in users:
            user_id = user.get("id_str")
            if user_id:
                self._cached_users[user_id] = user
            if user.get("screen_name"):
                self._cached_users[user["screen_name"].lower()] = user
            if user_id == self._viewer_id:
                self.logged_in_user = dict(user)
        return tweets, users

    async def fetch_graphql_direct(
        self, page_url: str, operations: Tuple[str, ...]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Fetch one web GraphQL operation over a reused HTTP session."""
        parsed = urlparse(page_url)
        page_path = parsed.path.rstrip("/")
        operation = next((name for name in operations if name in self._query_ids), None)
        variables: Dict[str, Any]
        if any(name in operations for name in ("HomeTimeline", "HomeLatestTimeline", "Viewer", "Account")):
            operation = "HomeTimeline"
            variables = {
                "count": 40,
                "includePromotedContent": False,
                "latestControlAvailable": True,
                "withCommunity": True,
                "seenTweetIds": [],
                "requestContext": "launch",
            }
        elif "SearchTimeline" in operations:
            operation = "SearchTimeline"
            query = parse_qs(parsed.query).get("q", [""])[0]
            variables = {"rawQuery": query, "count": 40, "querySource": "typed_query", "product": "Latest"}
        elif "TweetDetail" in operations:
            operation = "TweetDetail"
            status_id = page_path.rsplit("/", 1)[-1]
            variables = {"focalTweetId": status_id, "referrer": "home", "withCommunity": True}
        else:
            screen_name = page_path.strip("/").split("/")[0]
            if screen_name in {"home", "search", "i", "explore"}:
                return [], []
            user = self._cached_users.get(screen_name.lower())
            if not user:
                data = await self._direct_graphql(
                    "UserByScreenName",
                    {"screen_name": screen_name, "withSafetyModeUserFields": True, "withSuperFollowsUserFields": True},
                )
                if data:
                    _, found_users = self._remember_graphql(data)
                    user = next((item for item in found_users if item.get("screen_name", "").lower() == screen_name.lower()), None)
            user_id = (user or {}).get("id_str")
            if not user_id:
                return [], []
            if "UserTweets" in operations:
                operation = "UserTweets"
                variables = {"userId": user_id, "count": 40, "includePromotedContent": False, "withVoice": True, "withV2Timeline": True}
            elif "Likes" in operations:
                operation = "Likes"
                variables = {"userId": user_id, "count": 40, "includePromotedContent": False}
            elif "Following" in operations or "Followers" in operations:
                operation = "Following" if "Following" in operations else "Followers"
                variables = {"userId": user_id, "count": 100, "includePromotedContent": False}
            else:
                operation = "UserByScreenName"
                variables = {"screen_name": screen_name}
        if not operation:
            return [], []
        data = await self._direct_graphql(operation, variables)
        return self._remember_graphql(data) if data else ([], [])

    async def fetch_user_by_screen_name_direct(self, screen_name: str) -> Optional[Dict[str, Any]]:
        data = await self._direct_graphql(
            "UserByScreenName",
            {"screen_name": screen_name, "withSafetyModeUserFields": True, "withSuperFollowsUserFields": True},
        )
        if not data:
            return None
        _, users = self._remember_graphql(data)
        return next(
            (user for user in users if user.get("screen_name", "").lower() == screen_name.lower()),
            users[0] if users else None,
        )

    async def extract_session_from_browser(self) -> Tuple[str, str]:
        """Auto-extract auth_token and ct0 from Chrome persistent profile."""
        async with self._lock:
            if self.auth_token and self.ct0:
                return self.auth_token, self.ct0

            logger.info("[Twitter] Launching Chrome to inspect Twitter session cookies...")
            pw = None
            context = None
            try:
                pw = await async_playwright().start()
                TWITTER_PROFILE_PATH.mkdir(parents=True, exist_ok=True)
                launch_opts: Dict[str, Any] = {
                    "user_data_dir": str(TWITTER_PROFILE_PATH),
                    "headless": self.chrome_headless,
                    "no_viewport": True,
                    "args": [
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                }
                if CHROME_PATH.exists():
                    launch_opts["channel"] = "chrome"

                context = await pw.chromium.launch_persistent_context(
                    **launch_opts,
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                )

                page = context.pages[0] if context.pages else await context.new_page()
                try:
                    await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=12000)
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.debug(f"[Twitter] Chrome navigation note: {e}")

                cookies = await context.cookies()
                for c in cookies:
                    name = c.get("name")
                    val = c.get("value", "")
                    if name == "auth_token" and val:
                        self.auth_token = val
                    elif name == "ct0" and val:
                        self.ct0 = val

                if self.auth_token:
                    logger.info("[Twitter] Successfully borrowed Twitter auth_token from Chrome session!")
                    if self.config:
                        self.config.services.twitter_auth_token = self.auth_token
                        self.config.services.twitter_ct0 = self.ct0
                        try:
                            from src.utils import update_config_file
                            update_config_file(self.config)
                        except Exception as e:
                            logger.warning(f"[Twitter] Failed to save config: {e}")
                else:
                    logger.info("[Twitter] No active auth_token found in Chrome. Login to x.com in Chrome to link your account.")
            except Exception as e:
                logger.warning(f"[Twitter] Error accessing Chrome session: {e}")
            finally:
                if context:
                    await context.close()
                if pw:
                    await pw.stop()

            return self.auth_token, self.ct0

    async def fetch_graphql_via_browser(
        self, page_url: str, operations: Tuple[str, ...]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Load an authenticated X page and adapt its GraphQL tweet/user responses."""
        cache_key = page_url + "|" + ",".join(operations)
        cached = self._browser_cache.get(cache_key)
        if cached and time.time() - cached[0] < 30:
            return cached[1], cached[2]
        # A single persistent Chrome profile cannot be driven safely by several
        # simultaneous API requests. Serializing page loads also prevents the
        # app's startup fan-out from opening a browser for every endpoint.
        await self._browser_fetch_lock.acquire()
        cached = self._browser_cache.get(cache_key)
        if cached and time.time() - cached[0] < 30:
            self._browser_fetch_lock.release()
            return cached[1], cached[2]
        pw = None
        context = None
        captured_tweets: List[Dict[str, Any]] = []
        captured_users: List[Dict[str, Any]] = []

        try:
            pw = await async_playwright().start()
            TWITTER_PROFILE_PATH.mkdir(parents=True, exist_ok=True)
            launch_opts: Dict[str, Any] = {
                "user_data_dir": str(TWITTER_PROFILE_PATH),
                "headless": self.chrome_headless,
                "no_viewport": True,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            }
            if CHROME_PATH.exists():
                launch_opts["channel"] = "chrome"

            context = await pw.chromium.launch_persistent_context(
                **launch_opts,
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            )

            # Inject session cookies if configured
            if self.auth_token:
                cookie_entries = [
                    {"name": "auth_token", "value": self.auth_token, "domain": ".x.com", "path": "/"},
                    {"name": "auth_token", "value": self.auth_token, "domain": ".twitter.com", "path": "/"},
                ]
                if self.ct0:
                    cookie_entries.extend([
                        {"name": "ct0", "value": self.ct0, "domain": ".x.com", "path": "/"},
                        {"name": "ct0", "value": self.ct0, "domain": ".twitter.com", "path": "/"},
                    ])
                await context.add_cookies(cookie_entries)

            page = context.pages[0] if context.pages else await context.new_page()

            async def handle_response(response):
                nonlocal captured_tweets
                url = response.url
                if "graphql" in url and ("*" in operations or any(kw in url for kw in operations)):
                    try:
                        data = await response.json()
                        captured_users.extend(extract_users_from_graphql(data))
                        viewer_id = extract_viewer_id_from_graphql(data)
                        if viewer_id:
                            self._viewer_id = viewer_id
                            captured_users.extend(
                                user for user in extract_users_from_graphql(data)
                                if user.get("id_str") == viewer_id
                            )
                        extracted = extract_tweets_from_graphql(data)
                        if extracted:
                            logger.info(f"[Twitter] Intercepted {len(extracted)} real tweets from Twitter GraphQL!")
                            captured_tweets.extend(extracted)
                    except Exception:
                        pass

            page.on("response", handle_response)

            try:
                await page.goto(page_url, wait_until="networkidle", timeout=10000)
            except Exception:
                pass

            # Wait briefly for responses to settle
            for _ in range(5):
                if captured_tweets:
                    break
                await asyncio.sleep(1)

        except Exception as e:
            logger.warning(f"[Twitter] Failed to fetch timeline via browser: {e}")
        finally:
            if context:
                await context.close()
            if pw:
                await pw.stop()

        self._browser_cache[cache_key] = (time.time(), captured_tweets, captured_users)
        self._browser_fetch_lock.release()
        return captured_tweets, captured_users

    async def fetch_graphql_tweets_via_browser(
        self, page_url: str, operations: Tuple[str, ...]
    ) -> List[Dict[str, Any]]:
        direct_tweets, direct_users = await self.fetch_graphql_direct(page_url, operations)
        if direct_tweets or direct_users:
            tweets = direct_tweets
            users = direct_users
        elif not self.auth_token:
            tweets, users = await self.fetch_graphql_via_browser(page_url, operations)
        else:
            tweets, users = [], []
        for user in users:
            self._cached_users[user["id_str"]] = user
            if user.get("screen_name"):
                self._cached_users[user["screen_name"].lower()] = user
            if user.get("id_str") == self._viewer_id:
                self.logged_in_user = dict(user)
        unique = {tweet["id_str"]: tweet for tweet in tweets if tweet.get("id_str")}
        return list(unique.values())

    async def fetch_graphql_users_via_browser(
        self, page_url: str, operations: Tuple[str, ...]
    ) -> List[Dict[str, Any]]:
        _, users = await self.fetch_graphql_direct(page_url, operations)
        if not users and not self.auth_token:
            _, users = await self.fetch_graphql_via_browser(page_url, operations)
        unique = {u["id_str"]: u for u in users if u.get("id_str")}
        for user in unique.values():
            self._cached_users[user["id_str"]] = user
            if user.get("screen_name"):
                self._cached_users[user["screen_name"].lower()] = user
        return list(unique.values())

    async def fetch_timeline_via_browser(self) -> List[Dict[str, Any]]:
        return await self.fetch_graphql_tweets_via_browser(
            "https://x.com/home", ("HomeTimeline", "HomeLatestTimeline", "UserTweets", "Viewer", "Account")
        )

    async def fetch_search_via_browser(self, query: str) -> List[Dict[str, Any]]:
        search_url = "https://x.com/search?" + urlencode({"q": query, "src": "typed_query"})
        return await self.fetch_graphql_tweets_via_browser(search_url, ("SearchTimeline",))

    async def fetch_user_search_via_browser(self, query: str) -> List[Dict[str, Any]]:
        search_url = "https://x.com/search?" + urlencode(
            {"q": query, "src": "typed_query", "f": "user"}
        )
        return await self.fetch_graphql_users_via_browser(
            search_url, ("SearchTimeline", "UserByScreenName")
        )

    async def fetch_user_tweets_via_browser(self, screen_name: str) -> List[Dict[str, Any]]:
        return await self.fetch_graphql_tweets_via_browser(
            f"https://x.com/{screen_name}", ("UserTweets", "UserTweetsAndReplies")
        )

    async def fetch_likes_via_browser(self, screen_name: str) -> List[Dict[str, Any]]:
        return await self.fetch_graphql_tweets_via_browser(
            f"https://x.com/{screen_name}/likes", ("Likes", "LikedTweets")
        )

    async def fetch_user_list_via_browser(
        self, screen_name: str, following: bool
    ) -> List[Dict[str, Any]]:
        operation = "Following" if following else "Followers"
        return await self.fetch_graphql_users_via_browser(
            f"https://x.com/{screen_name}/{'following' if following else 'followers'}",
            (operation,),
        )

    async def get_home_timeline(self) -> List[Dict[str, Any]]:
        """Retrieve real tweets using cache, direct session, or Chrome scraping."""
        now = time.time()
        # Return cached tweets if still fresh (60 seconds)
        if self._cache_time and (now - self._cache_time < 60.0):
            return self.posted_tweets + self._cached_timeline

        # 1. If tokens not configured, try extracting them once from the browser
        if not self.auth_token:
            await self.extract_session_from_browser()

        # 2. If session is available, fetch via browser automation
        tweets: List[Dict[str, Any]] = []
        if self.auth_token:
            tweets = await self.fetch_timeline_via_browser()

        if tweets:
            self._cached_timeline = tweets
            self._cache_time = now
            return self.posted_tweets + tweets

        # An unavailable session must not be presented as a fake timeline. The
        # caller can retry after the browser session has been repaired.
        self._cached_timeline = []
        self._cache_time = now
        return list(self.posted_tweets)

    async def request(self, flow: http.HTTPFlow) -> bool:
        if not is_twitter_request(flow):
            return False

        url = flow.request.url
        host = (urlparse(url).hostname or "").lower().rstrip(".")
        path = urlparse(url).path
        method = flow.request.method.upper()

        logger.info(f"[Twitter] Intercepting {method} {url}")

        # 1. Crashlytics handling (settings.crashlytics.com)
        if host in CRASHLYTICS_HOSTS:
            flow.response = self._json_response(
                {
                    "settings_version": 2,
                    "features": {
                        "collect_reports": False,
                        "collect_logged_exceptions": False,
                        "collect_analytics": False,
                    },
                }
            )
            return True

        # 2. Decider / Feature flags (mobile.twitter.com/ios/decider.json)
        if "decider.json" in path:
            # Setting spdy fraction to 0 ensures client uses standard HTTP proxy
            flow.response = self._json_response(
                {
                    "deciders": {
                        "spdy_v3r4_enabled_user_fraction": 0,
                        "spdy_enabled_user_fraction": 0,
                        "hometimeline_conversations_enabled": 0,
                    },
                    "experiments": {},
                }
            )
            return True

        # 3. OAuth 1.0a xAuth Login (POST /oauth/access_token)
        if "/oauth/access_token" in path or path.endswith("/access_token"):
            body_bytes = flow.request.content or b""
            body_str = body_bytes.decode("utf-8", errors="ignore")
            form_data = parse_qs(body_str)
            username = form_data.get("x_auth_username", [self.logged_in_user["screen_name"]])[0]

            self.logged_in_user["screen_name"] = username
            self.logged_in_user["name"] = username

            # The legacy client only understands xAuth. Resolve that handshake
            # against the real web session before returning the compatibility
            # token, so the following users/lookup request has the real ID.
            if self.auth_token:
                await self._direct_verify_credentials()
            if self.auth_token and self.logged_in_user.get("id_str") == DEFAULT_USER["id_str"]:
                user = await self.fetch_user_by_screen_name_direct(username)
                if user:
                    self.logged_in_user = user
            if self.auth_token and self.logged_in_user.get("id_str") == DEFAULT_USER["id_str"]:
                await self.fetch_graphql_tweets_via_browser(
                    "https://x.com/home", ("Viewer", "Account", "HomeTimeline")
                )

            logger.info(f"[Twitter] Issued xAuth compatibility token for user: {self.logged_in_user.get('screen_name', username)}")
            token_response = (
                f"oauth_token=legacy_token_12345678"
                f"&oauth_token_secret=legacy_secret_87654321"
                f"&user_id={self.logged_in_user['id']}"
                f"&screen_name={username}"
                f"&x_auth_expires=0"
            )
            flow.response = self._text_response(token_response)
            return True

        # 4. Verify Credentials (GET /1.1/account/verify_credentials.json)
        if "account/verify_credentials.json" in path:
            if self.auth_token and self.logged_in_user.get("id_str") == DEFAULT_USER["id_str"]:
                await self._direct_verify_credentials()
            if self.auth_token and self.logged_in_user.get("id_str") == DEFAULT_USER["id_str"]:
                await self.fetch_graphql_tweets_via_browser(
                    "https://x.com/home", ("Viewer", "Account", "HomeTimeline")
                )
            if self.auth_token and self.logged_in_user.get("id_str") == DEFAULT_USER["id_str"]:
                username = self.logged_in_user.get("screen_name", "")
                if username and username != DEFAULT_USER["screen_name"]:
                    user = await self.fetch_user_by_screen_name_direct(username)
                    if user:
                        self.logged_in_user = user
            if self.auth_token and self.logged_in_user.get("id_str") == DEFAULT_USER["id_str"]:
                flow.response = self._json_response(
                    {"errors": [{"message": "Twitter session could not be verified"}]}, 401
                )
                return True
            flow.response = self._json_response(self.logged_in_user)
            return True

        # 5. Configuration (GET /1.1/help/configuration.json)
        if "help/configuration.json" in path:
            flow.response = self._json_response(TWITTER_CONFIG)
            return True

        # 6. Experiments (GET /1.1/help/experiments.json)
        if "help/experiments.json" in path or "experimentation" in path:
            flow.response = self._json_response({"experiments": []})
            return True

        # 7a. Home Timeline flat (GET /1.1/statuses/home_timeline.json) — flat array
        if "statuses/home_timeline.json" in path:
            all_tweets = await self.get_home_timeline()
            flow.response = self._json_response(all_tweets)
            return True

        # 7c. Search (Twitter 5.12 uses search/universal.json).
        if "search/universal.json" in path or "search/tweets.json" in path:
            params = parse_qs(urlparse(url).query)
            query = params.get("q", params.get("query", [""]))[0]
            tweets: List[Dict[str, Any]] = []
            if query:
                if not self.auth_token:
                    await self.extract_session_from_browser()
                if self.auth_token:
                    tweets = await self.fetch_search_via_browser(query)
            search_users = {
                str(tweet.get("user", {}).get("id_str")): tweet.get("user")
                for tweet in tweets
                if tweet.get("user", {}).get("id_str")
            }
            flow.response = self._json_response(
                {
                    "metadata": {"cursor": ""},
                    "modules": [
                        {"type": "status", "status": {"data": tweet}}
                        for tweet in tweets
                    ],
                    "statuses": tweets,
                    "search_metadata": {
                        "query": query,
                        "count": len(tweets),
                        "max_id": tweets[-1]["id"] if tweets else 0,
                        "since_id": 0,
                    },
                    "users": list(search_users.values()),
                }
            )
            return True

        # 7b. Conversations timeline (GET /1.1/timeline/home.json)
        # TwitterConversationsTimelineStream expects:
        #   { "timeline": [...], "users": {...}, "statuses": [...] }
        # where "statuses" is the flat tweet list and "users" is a dict keyed by id_str
        if "timeline/home.json" in path:
            all_tweets = await self.get_home_timeline()
            users: Dict[str, Any] = {}
            for t in all_tweets:
                u = t.get("user", {})
                uid = u.get("id_str", "")
                if uid:
                    users[uid] = u
            # Conversation timeline entries refer to statuses by tweet_id.
            status_map = {
                str(t.get("id_str", t.get("id", ""))): t for t in all_tweets
            }
            response_body = {
                "metadata": {
                    "min_position": next(iter(status_map), ""),
                    "max_position": next(reversed(status_map), "") if status_map else "",
                },
                "timeline": [
                    {
                        "type": "timeline_conversation",
                        "id": tweet_id,
                        "tweet_id": tweet_id,
                        "sort_index": tweet_id,
                        "statuses": [tweet_id],
                        "status_ids": [tweet_id],
                    }
                    for tweet_id in status_map
                ],
                "users": users,
                "statuses": status_map,
                "next_cursor": "",
                "previous_cursor": "",
            }
            flow.response = self._json_response(response_body)
            return True

        # 8. User Timeline (GET /1.1/statuses/user_timeline.json)
        if "statuses/user_timeline.json" in path:
            params = parse_qs(urlparse(url).query)
            screen_name = params.get("screen_name", [""])[0].lstrip("@").lower()
            user_id = params.get("user_id", [""])[0]
            user = self._cached_users.get(screen_name) or self._cached_users.get(user_id)
            if not screen_name and self.logged_in_user.get("screen_name"):
                screen_name = self.logged_in_user["screen_name"]
            if not screen_name and user:
                screen_name = user.get("screen_name", "").lower()
            user_tweets = self._cached_user_tweets.get(screen_name, [])
            if screen_name and not user_tweets and self.auth_token:
                user_tweets = await self.fetch_user_tweets_via_browser(screen_name)
                self._cached_user_tweets[screen_name] = user_tweets
            if user:
                self._cached_users[screen_name] = user
            if not user_tweets:
                user_tweets = self.posted_tweets
            flow.response = self._json_response(user_tweets)
            return True

        if "statuses/mentions_timeline.json" in path:
            tweets = await self.get_home_timeline()
            username = self.logged_in_user.get("screen_name", "").lower()
            mentions = [
                tweet for tweet in tweets
                if username and f"@{username}" in tweet.get("text", "").lower()
            ]
            flow.response = self._json_response(mentions)
            return True

        # 8b. User lists and profile lookups.
        if "users/lookup.json" in path:
            params = parse_qs(urlparse(url).query)
            names = [n for n in params.get("screen_name", [""])[0].split(",") if n]
            ids = [n for n in params.get("user_id", [""])[0].split(",") if n]
            users = [self._cached_users[key.lower()] for key in names if key.lower() in self._cached_users]
            users.extend(self._cached_users[key] for key in ids if key in self._cached_users)
            if ids and not users and self.auth_token:
                await self.fetch_graphql_users_via_browser(
                    "https://x.com/home", ("Viewer", "Account", "HomeTimeline")
                )
                users.extend(
                    self._cached_users[key]
                    for key in ids
                    if key in self._cached_users
                )
                if not users and self.logged_in_user.get("id_str") != DEFAULT_USER["id_str"]:
                    users.append(dict(self.logged_in_user))
            for name in names:
                if name.lower() not in self._cached_users and self.auth_token:
                    found = await self.fetch_graphql_users_via_browser(
                        f"https://x.com/{name}", ("UserByScreenName", "UserTweets")
                    )
                    users.extend(found[:1])
            flow.response = self._json_response(users)
            return True

        if "users/show.json" in path:
            params = parse_qs(urlparse(url).query)
            key = (params.get("screen_name", [""])[0] or params.get("user_id", [""])[0]).lower()
            user = self._cached_users.get(key)
            if not user and key and self.auth_token:
                found = await self.fetch_graphql_users_via_browser(
                    f"https://x.com/{key}", ("UserByScreenName", "UserTweets")
                )
                user = found[0] if found else None
            flow.response = self._json_response(user or {"errors": [{"message": "User not found"}]}, 200 if user else 404)
            return True

        if "users/search.json" in path:
            params = parse_qs(urlparse(url).query)
            query = params.get("q", [""])[0]
            users = []
            if query and self.auth_token:
                users = await self.fetch_user_search_via_browser(query)
            flow.response = self._json_response(users)
            return True

        if "users/profile_banner.json" in path:
            params = parse_qs(urlparse(url).query)
            key = (params.get("screen_name", [""])[0] or params.get("user_id", [""])[0]).lower()
            user = self._cached_users.get(key)
            banner = (user or {}).get("profile_banner_url")
            if banner:
                flow.response = self._json_response(
                    {
                        "sizes": {
                            size: {"w": width, "h": height, "url": banner}
                            for size, width, height in (
                                ("mobile", 320, 100),
                                ("ipad", 1024, 300),
                                ("web", 520, 260),
                                ("web_retina", 1040, 520),
                            )
                        }
                    }
                )
            else:
                flow.response = self._json_response({"sizes": {}})
            return True

        if "users/reverse_lookup.json" in path:
            params = parse_qs(urlparse(url).query)
            ids = [value for value in params.get("user_id", [""])[0].split(",") if value]
            flow.response = self._json_response(
                [self._cached_users[user_id] for user_id in ids if user_id in self._cached_users]
            )
            return True

        if (
            "friends/list.json" in path
            or "followers/list.json" in path
            or "friends/following/list.json" in path
        ):
            params = parse_qs(urlparse(url).query)
            screen_name = params.get("screen_name", [""])[0].lstrip("@").lower()
            if not screen_name:
                screen_name = self.logged_in_user.get("screen_name", "").lower()
            users = []
            if screen_name and self.auth_token:
                users = await self.fetch_user_list_via_browser(
                    screen_name, "friends/list.json" in path or "friends/following/list.json" in path
                )
            flow.response = self._json_response(
                {"users": users, "next_cursor": 0, "previous_cursor": 0}
            )
            return True

        if "friends/ids.json" in path or "followers/ids.json" in path:
            params = parse_qs(urlparse(url).query)
            screen_name = params.get("screen_name", [""])[0].lstrip("@").lower()
            if not screen_name:
                screen_name = self.logged_in_user.get("screen_name", "").lower()
            users = []
            if screen_name and self.auth_token:
                users = await self.fetch_user_list_via_browser(
                    screen_name, "friends/ids.json" in path
                )
            ids = [user["id_str"] for user in users if user.get("id_str")]
            flow.response = self._json_response(
                {"ids": ids, "next_cursor": 0, "previous_cursor": 0}
            )
            return True

        if "statuses/media_timeline.json" in path:
            params = parse_qs(urlparse(url).query)
            screen_name = params.get("screen_name", [""])[0].lstrip("@").lower()
            tweets = self._cached_user_tweets.get(screen_name, [])
            if screen_name and not tweets and self.auth_token:
                tweets = await self.fetch_user_tweets_via_browser(screen_name)
                self._cached_user_tweets[screen_name] = tweets
            flow.response = self._json_response(
                [t for t in tweets if t.get("entities", {}).get("media")]
            )
            return True

        status_match = re.search(r"/statuses/show/(\d+)\.json$", path)
        if status_match:
            status_id = status_match.group(1)
            tweet = next(
                (t for t in self._cached_timeline + self.posted_tweets if t.get("id_str") == status_id),
                None,
            )
            if not tweet and self.auth_token:
                tweets, _ = await self.fetch_graphql_via_browser(
                    f"https://x.com/i/web/status/{status_id}", ("TweetDetail", "TweetResult")
                )
                tweet = next((item for item in tweets if item.get("id_str") == status_id), None)
            flow.response = self._json_response(
                tweet or {"errors": [{"message": "Tweet not found"}]}, 200 if tweet else 404
            )
            return True

        if "conversation/show.json" in path:
            params = parse_qs(urlparse(url).query)
            status_id = params.get("id", [""])[0]
            tweets = []
            if status_id and self.auth_token:
                tweets, users = await self.fetch_graphql_via_browser(
                    f"https://x.com/i/web/status/{status_id}", ("TweetDetail", "TweetResult")
                )
                for user in users:
                    self._cached_users[user["id_str"]] = user
            status_map = {tweet["id_str"]: tweet for tweet in tweets if tweet.get("id_str")}
            flow.response = self._json_response(
                {
                    "timeline": [
                        {"type": "timeline_conversation", "id": key, "statuses": [key]}
                        for key in status_map
                    ],
                    "users": {
                        user["id_str"]: user
                        for tweet in tweets
                        if (user := tweet.get("user", {})).get("id_str")
                    },
                    "statuses": status_map,
                }
            )
            return True

        # 9. Post / Update Status (POST /1.1/statuses/update.json)
        if "statuses/update.json" in path and method == "POST":
            logger.info("[Twitter] Passing status update upstream; no local fake post is created")
            return False

        # 10. Notifications / Activity (GET /1.1/activity/about_me.json)
        if "activity/about_me" in path:
            flow.response = self._json_response([])
            return True

        if "activity/by_friends" in path or "activity/mentions" in path:
            flow.response = self._json_response([])
            return True

        if "statuses/" in path and path.endswith("/activity/summary.json"):
            flow.response = self._json_response({"favorited": [], "retweeted": []})
            return True

        if "friendships/show.json" in path:
            params = parse_qs(urlparse(url).query)
            source_id = params.get("source_id", [self.logged_in_user.get("id_str", "")])[0]
            target_id = params.get("target_id", [""])[0]
            target_name = params.get("target_screen_name", [""])[0]
            target = self._cached_users.get(target_id) or self._cached_users.get(target_name.lower())
            flow.response = self._json_response(
                {
                    "relationship": {
                        "source": {
                            "id": int(source_id) if source_id.isdigit() else 0,
                            "id_str": source_id,
                            "screen_name": self.logged_in_user.get("screen_name", ""),
                            "following": bool(target and target.get("following")),
                            "followed_by": bool(target and target.get("followed_by")),
                            "can_dm": True,
                        },
                        "target": target or {
                            "id": int(target_id) if target_id.isdigit() else 0,
                            "id_str": target_id,
                            "screen_name": target_name,
                        },
                    }
                }
            )
            return True

        # These two endpoints are polled repeatedly during startup. Returning
        # {} with HTTP 200 makes the app retry them continuously.
        if path == "/1.1/users/suggestions.json":
            flow.response = self._json_response([])
            return True

        if path == "/1.1/saved_searches/list.json":
            flow.response = self._json_response([])
            return True

        if "friendships/lookup.json" in path:
            params = parse_qs(urlparse(url).query)
            names = [name.lstrip("@").lower() for name in params.get("screen_name", [""])[0].split(",") if name]
            relationships = []
            for name in names:
                user = self._cached_users.get(name)
                relationships.append(
                    {
                        "id": user.get("id", 0) if user else 0,
                        "id_str": user.get("id_str", "") if user else "",
                        "screen_name": user.get("screen_name", name) if user else name,
                        "connections": [
                            connection
                            for connection, enabled in (
                                ("following", bool(user and user.get("following"))),
                                ("followed_by", bool(user and user.get("followed_by"))),
                            )
                            if enabled
                        ],
                    }
                )
            flow.response = self._json_response(relationships)
            return True

        if "lists/ownerships.json" in path or "lists/subscriptions.json" in path:
            flow.response = self._json_response([])
            return True

        if "account/push_destinations" in path:
            flow.response = self._json_response([])
            return True

        if "prompts/suggest.json" in path or "prompts/record_event.json" in path:
            flow.response = self._json_response([])
            return True

        if any(term in path for term in (
            "/users/recommendations.json",
            "/users/lookup.json",
            "/friends/list.json",
            "/statuses/media_timeline.json",
        )):
            flow.response = self._json_response([])
            return True

        if "discover/universal.json" in path:
            flow.response = self._json_response(
                {"metadata": {}, "modules": [], "statuses": [], "users": []}
            )
            return True

        # 11. Direct Messages (GET /1.1/direct_messages.json, sent.json)
        if "direct_messages" in path:
            flow.response = self._json_response([])
            return True

        # 12. Favorites list (GET /1.1/favorites/list.json)
        if "favorites/list.json" in path:
            params = parse_qs(urlparse(url).query)
            screen_name = params.get("screen_name", [""])[0].lstrip("@").lower()
            if not screen_name:
                screen_name = self.logged_in_user.get("screen_name", "").lower()
            tweets = []
            if screen_name and self.auth_token:
                tweets = await self.fetch_likes_via_browser(screen_name)
            flow.response = self._json_response(tweets)
            return True

        # 13. Trends (GET /1.1/trends/...)
        if "trends" in path:
            flow.response = self._json_response([])
            return True

        # 14. Users show / lookup
        if "users/show.json" in path:
            flow.response = self._json_response(self.logged_in_user)
            return True

        # 15. Promoted / Scribe / Tracking analytics endpoints
        if any(term in path for term in ["scribe", "promoted_content", "mobile_client_api", "feedback", "badge"]):
            flow.response = self._json_response({})
            return True

        # Let the real upstream service answer endpoints we have not translated.
        # Returning a fabricated 404 makes the client permanently believe that
        # the feature is unavailable and prevents future compatibility fixes.
        logger.info(f"[Twitter] Unsupported endpoint: {method} {path}")
        return False

    def response(self, flow: http.HTTPFlow):
        pass
