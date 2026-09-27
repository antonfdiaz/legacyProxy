import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from mitmproxy import http
from src.services.twitter import (
    TwitterProxy,
    extract_tweets_from_graphql,
    graphql_tweet_to_v1,
    is_twitter_request,
)


class DummyFlow:
    def __init__(self, method: str, url: str, content: bytes = b"", headers: dict = None):
        self.request = MagicMock()
        self.request.method = method
        self.request.url = url
        self.request.path = url
        self.request.content = content
        self.request.pretty_host = url.split("://")[1].split("/")[0] if "://" in url else ""
        self.request.headers = headers or {}
        self.response = None


class TwitterProxyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.proxy = TwitterProxy()

    def test_is_twitter_request(self):
        flow_api = DummyFlow("GET", "https://api.twitter.com/1.1/account/verify_credentials.json")
        self.assertTrue(is_twitter_request(flow_api))

        flow_decider = DummyFlow("GET", "http://mobile.twitter.com/ios/decider.json")
        self.assertTrue(is_twitter_request(flow_decider))

        flow_crashlytics = DummyFlow("GET", "https://settings.crashlytics.com/spi/v2/platforms/ios/apps/settings")
        self.assertTrue(is_twitter_request(flow_crashlytics))

        flow_ua = DummyFlow(
            "GET", "https://example.com/api", headers={"User-Agent": "Twitter/5.12 (iPhone; iOS 7.1.2; Scale/2.00)"}
        )
        self.assertTrue(is_twitter_request(flow_ua))

        flow_other = DummyFlow("GET", "https://google.com/search")
        self.assertFalse(is_twitter_request(flow_other))

    async def test_crashlytics_response(self):
        flow = DummyFlow("GET", "https://settings.crashlytics.com/settings")
        handled = await self.proxy.request(flow)
        self.assertTrue(handled)
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 200)
        data = json.loads(flow.response.content.decode("utf-8"))
        self.assertEqual(data.get("settings_version"), 2)

    async def test_decider_response(self):
        flow = DummyFlow("GET", "http://mobile.twitter.com/ios/decider.json")
        handled = await self.proxy.request(flow)
        self.assertTrue(handled)
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 200)
        data = json.loads(flow.response.content.decode("utf-8"))
        self.assertEqual(data.get("deciders", {}).get("spdy_v3r4_enabled_user_fraction"), 0)

    async def test_xauth_login(self):
        flow = DummyFlow(
            "POST",
            "https://api.twitter.com/oauth/access_token",
            content=b"x_auth_username=retro_geek&x_auth_password=mypassword&x_auth_mode=client_auth",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        handled = await self.proxy.request(flow)
        self.assertTrue(handled)
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 200)
        resp_text = flow.response.content.decode("utf-8")
        self.assertIn("oauth_token=", resp_text)
        self.assertIn("oauth_token_secret=", resp_text)
        self.assertIn("screen_name=retro_geek", resp_text)

    async def test_verify_credentials(self):
        login_flow = DummyFlow(
            "POST",
            "https://api.twitter.com/oauth/access_token",
            content=b"x_auth_username=steve_jobs&x_auth_mode=client_auth",
        )
        await self.proxy.request(login_flow)

        flow = DummyFlow("GET", "https://api.twitter.com/1.1/account/verify_credentials.json")
        handled = await self.proxy.request(flow)
        self.assertTrue(handled)
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 200)
        data = json.loads(flow.response.content.decode("utf-8"))
        self.assertEqual(data["screen_name"], "steve_jobs")
        self.assertEqual(data["name"], "steve_jobs")

    async def test_help_configuration(self):
        flow = DummyFlow("GET", "https://api.twitter.com/1.1/help/configuration.json")
        handled = await self.proxy.request(flow)
        self.assertTrue(handled)
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 200)
        data = json.loads(flow.response.content.decode("utf-8"))
        self.assertIn("photo_sizes", data)
        self.assertIn("short_url_length", data)

    def test_graphql_tweet_to_v1(self):
        mock_raw = {
            "__typename": "Tweet",
            "rest_id": "1840000000000000001",
            "core": {
                "user_results": {
                    "result": {
                        "rest_id": "999888",
                        "legacy": {
                            "name": "Apple Fan",
                            "screen_name": "apple_fan",
                            "profile_image_url_https": "https://pbs.twimg.com/avatar.jpg",
                            "followers_count": 120,
                            "friends_count": 80,
                            "verified": True,
                        },
                    }
                }
            },
            "legacy": {
                "created_at": "Sat Sep 27 12:00:00 +0000 2026",
                "full_text": "iPhone 4S on iOS 7.1.2 is legendary.",
                "favorite_count": 55,
                "retweet_count": 12,
            },
        }

        v1 = graphql_tweet_to_v1(mock_raw)
        self.assertIsNotNone(v1)
        self.assertEqual(v1["id_str"], "1840000000000000001")
        self.assertEqual(v1["text"], "iPhone 4S on iOS 7.1.2 is legendary.")
        self.assertEqual(v1["favorite_count"], 55)
        self.assertEqual(v1["user"]["screen_name"], "apple_fan")
        self.assertEqual(v1["user"]["name"], "Apple Fan")
        self.assertTrue(v1["user"]["verified"])

    def test_extract_tweets_from_graphql(self):
        mock_payload = {
            "data": {
                "home": {
                    "home_timeline_urt": {
                        "instructions": [
                            {
                                "type": "TimelineAddEntries",
                                "entries": [
                                    {
                                        "entryId": "tweet-1",
                                        "content": {
                                            "itemContent": {
                                                "tweet_results": {
                                                    "result": {
                                                        "__typename": "Tweet",
                                                        "rest_id": "1001",
                                                        "core": {
                                                            "user_results": {
                                                                "result": {
                                                                    "rest_id": "50",
                                                                    "legacy": {"screen_name": "user1"},
                                                                }
                                                            }
                                                        },
                                                        "legacy": {"full_text": "First tweet"},
                                                    }
                                                }
                                            }
                                        },
                                    }
                                ],
                            }
                        ]
                    }
                }
            }
        }
        tweets = extract_tweets_from_graphql(mock_payload)
        self.assertEqual(len(tweets), 1)
        self.assertEqual(tweets[0]["id_str"], "1001")
        self.assertEqual(tweets[0]["text"], "First tweet")
        self.assertEqual(tweets[0]["user"]["screen_name"], "user1")

    async def test_home_timeline_default(self):
        with patch.object(self.proxy, "fetch_timeline_via_browser", new=AsyncMock(return_value=[])):
            with patch.object(self.proxy, "extract_session_from_browser", new=AsyncMock(return_value=("", ""))):
                flow = DummyFlow("GET", "https://api.twitter.com/1.1/statuses/home_timeline.json")
                handled = await self.proxy.request(flow)
                self.assertTrue(handled)
                self.assertIsNotNone(flow.response)
                self.assertEqual(flow.response.status_code, 200)
                tweets = json.loads(flow.response.content.decode("utf-8"))
                self.assertIsInstance(tweets, list)
                self.assertGreater(len(tweets), 0)
                self.assertIn("legacyProxy", tweets[0]["text"])

    async def test_update_status(self):
        flow = DummyFlow(
            "POST",
            "https://api.twitter.com/1.1/statuses/update.json",
            content=b"status=Hello%20from%20iPhone%204S!",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        handled = await self.proxy.request(flow)
        self.assertTrue(handled)
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 200)
        tweet = json.loads(flow.response.content.decode("utf-8"))
        self.assertEqual(tweet["text"], "Hello from iPhone 4S!")


if __name__ == "__main__":
    unittest.main()
