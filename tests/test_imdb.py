import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.imdb import IMDB_AMAZON_AD_CONFIG_JSON, IMDbProxy


class _Response:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class IMDbProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_config_disables_content_symphony(self):
        config = {
            "data": {
                "device_config": {
                    "features": {
                        "app_service_is_alive": {"enabled": False},
                        "contentSymphonyWidgets": {"enabled": True},
                        "reportAdMetrics": {"enabled": True},
                    },
                    "content_symphony_page_map": {"home": "homepage"},
                },
                "home_page": {
                    "sections": [
                        {
                            "items": [
                                {"class": "IMDb.ContentSymphonyWidget"},
                                {"class": "IMHeroCarouselWidget"},
                            ]
                        }
                    ]
                },
                "title_page": {
                    "sections": [
                        {
                            "items": [
                                {"class": "IMDb.ContentSymphonyWidget"},
                                {"class": "IMTitlePageNativeAdWidget"},
                            ]
                        }
                    ]
                },
            }
        }
        body = json.dumps(config).encode()
        with patch("src.services.imdb.urllib.request.urlopen", return_value=_Response(body)):
            cleaned = await IMDbProxy()._get_cleaned_config("https://example.test/iphone.json.gz")

        cleaned_config = json.loads(cleaned)
        device_config = cleaned_config["data"]["device_config"]
        self.assertTrue(device_config["features"]["app_service_is_alive"]["enabled"])
        self.assertFalse(device_config["features"]["contentSymphonyWidgets"]["enabled"])
        self.assertFalse(device_config["features"]["reportAdMetrics"]["enabled"])
        self.assertEqual(device_config["content_symphony_page_map"], {})
        self.assertEqual(
            cleaned_config["data"]["home_page"]["sections"][0]["items"],
            [{"class": "IMHeroCarouselWidget"}],
        )
        self.assertEqual(cleaned_config["data"]["title_page"]["sections"], [])

    async def test_config_response_is_not_cached(self):
        proxy = IMDbProxy()
        flow = MagicMock()
        flow.request.pretty_host = "ios-app-config.media-imdb.com"
        flow.request.path = "/5.9.1/iphone.json.gz"
        flow.request.url = "https://ios-app-config.media-imdb.com/5.9.1/iphone.json.gz"
        proxy._get_cleaned_config = lambda url: asyncio.sleep(0, result=b"{}")

        self.assertTrue(await proxy.request(flow))
        self.assertEqual(flow.response.headers["Cache-Control"], "no-store")

    async def test_ad_config_is_forwarded_with_fresh_signature(self):
        proxy = IMDbProxy()
        flow = MagicMock()
        flow.request.pretty_host = "api.imdbws.com"
        flow.request.path = "/template/imdb-ios-writable/ad-config-v2.jstl/render"
        flow.request.url = (
            "https://api.imdbws.com/template/imdb-ios-writable/"
            "ad-config-v2.jstl/render?appversion=5.9.1"
        )
        flow.request.method = "GET"
        flow.request.raw_content = b""
        flow.request.headers = {"Authorization": "legacy signature"}
        proxy.get_credentials_async = AsyncMock()
        proxy.is_token_valid = MagicMock(return_value=True)
        proxy.sign_sigv4 = MagicMock(return_value={"Authorization": "fresh signature"})

        self.assertFalse(await proxy.request(flow))
        self.assertEqual(flow.request.headers["Authorization"], "fresh signature")
        proxy.sign_sigv4.assert_called_once_with("GET", flow.request.url, b"")

    async def test_amazon_ad_sdk_receives_a_valid_legacy_config(self):
        proxy = IMDbProxy()
        flow = MagicMock()
        flow.request.pretty_host = "mads.amazon-adsystem.com"
        flow.request.path = "/msdk/getConfig?dinfo=legacy"

        self.assertTrue(await proxy.request(flow))
        self.assertEqual(flow.response.raw_content, IMDB_AMAZON_AD_CONFIG_JSON)
        config = json.loads(flow.response.raw_content)
        self.assertEqual(config["adResourcePath"], "/e/msdk/ads")
        self.assertEqual(config["ttl"], "86400")
        self.assertFalse(config["sendGeo"])
        self.assertFalse(config["featureUseGPSAID"])

    async def test_amazon_viewability_script_is_served_locally(self):
        proxy = IMDbProxy()
        flow = MagicMock()
        flow.request.pretty_host = "dwxjayoxbnyrr.cloudfront.net"
        flow.request.path = "/amazon-ads-v2.viewablejs"

        self.assertTrue(await proxy.request(flow))
        self.assertEqual(flow.response.raw_content, b"")
        self.assertIn("application/javascript", flow.response.headers["Content-Type"])

    def test_applab_tls_failure_is_absorbed(self):
        proxy = IMDbProxy()
        flow = MagicMock()
        flow.request.pretty_host = "applab-sdk.amazon.com"

        self.assertTrue(proxy.error(flow))
        self.assertEqual(flow.response.status_code, 200)
