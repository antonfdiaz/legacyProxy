import unittest
from unittest.mock import MagicMock
from mitmproxy import http
from src.services.reddit import RedditProxy, REDDIT_APP_CONFIG_JSON

class TestRedditProxy(unittest.TestCase):
    def setUp(self):
        self.proxy = RedditProxy()

    def _create_flow(self, url, method="GET", headers=None):
        flow = MagicMock(spec=http.HTTPFlow)
        req = MagicMock(spec=http.Request)
        req.url = url
        req.method = method
        
        # parse host from url
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        req.pretty_host = parts.hostname or ""
        req.path = parts.path
        req.headers = headers or {}
        flow.request = req
        flow.response = None
        return flow

    def test_mobile_config_gateway_post(self):
        """Test POST https://gateway.reddit.com/redditmobile/1/ios/config is intercepted and returns 200 JSON."""
        flow = self._create_flow("https://gateway.reddit.com/redditmobile/1/ios/config", method="POST")
        result = self.proxy.request(flow)

        self.assertTrue(result)
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 200)
        self.assertEqual(flow.response.raw_content, REDDIT_APP_CONFIG_JSON)
        self.assertIn("application/json", flow.response.headers.get("Content-Type", ""))

    def test_mobile_config_www_get(self):
        """Test GET https://www.reddit.com/redditmobile/1/ios/config is intercepted and returns 200 JSON."""
        flow = self._create_flow("https://www.reddit.com/redditmobile/1/ios/config", method="GET")
        result = self.proxy.request(flow)

        self.assertTrue(result)
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 200)
        self.assertEqual(flow.response.raw_content, REDDIT_APP_CONFIG_JSON)

    def test_mobile_config_old_reddit_get(self):
        """Test GET https://old.reddit.com/redditmobile/1/ios/config returns 200 JSON instead of 404."""
        flow = self._create_flow("https://old.reddit.com/redditmobile/1/ios/config", method="GET")
        result = self.proxy.request(flow)

        self.assertTrue(result)
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 200)
        self.assertEqual(flow.response.raw_content, REDDIT_APP_CONFIG_JSON)

    def test_browser_web_redirect(self):
        """Test standard web browsing to www.reddit.com redirects to old.reddit.com."""
        flow = self._create_flow(
            "https://www.reddit.com/r/technology",
            method="GET",
            headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 8_4_1 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Version/8.0 Mobile/12H321 Safari/600.1.4"}
        )
        result = self.proxy.request(flow)

        self.assertTrue(result)
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 302)
        self.assertEqual(flow.response.headers["Location"], "https://old.reddit.com/r/technology")

    def test_app_user_agent_not_redirected(self):
        """Test requests with Reddit App User-Agent are not redirected to old.reddit.com."""
        flow = self._create_flow(
            "https://www.reddit.com/r/technology.json",
            method="GET",
            headers={"User-Agent": "Reddit/2.0.1 (iOS 8.4.1)"}
        )
        result = self.proxy.request(flow)

        self.assertFalse(result)
        self.assertIsNone(flow.response)

    def test_oauth_host_not_redirected(self):
        """Test requests to oauth.reddit.com are not redirected to old.reddit.com."""
        flow = self._create_flow("https://oauth.reddit.com/api/v1/me", method="GET", headers={"Authorization": "bearer token123"})
        result = self.proxy.request(flow)

        self.assertFalse(result)
        self.assertIsNone(flow.response)

    def test_access_token_post_not_redirected(self):
        """Test OAuth access_token POST is not redirected."""
        flow = self._create_flow("https://www.reddit.com/api/v1/access_token", method="POST")
        result = self.proxy.request(flow)

        self.assertFalse(result)
        self.assertIsNone(flow.response)

    def test_image_proxy_rewrite(self):
        """Test old.reddit.com/legacy-proxy-image/ rewriting."""
        flow = self._create_flow("https://old.reddit.com/legacy-proxy-image/xyz.jpg", method="GET")
        result = self.proxy.request(flow)

        self.assertTrue(result)
        self.assertEqual(flow.request.url, "https://preview.redd.it/xyz.jpg")

    def test_gallery_redirect(self):
        """Test gallery redirection to comments."""
        flow = self._create_flow("https://www.reddit.com/gallery/abc123", method="GET")
        result = self.proxy.request(flow)

        self.assertTrue(result)
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 302)
        self.assertEqual(flow.response.headers["Location"], "https://old.reddit.com/comments/abc123")

    def test_old_reddit_response_styling(self):
        """Test that old.reddit.com HTML responses receive mobile styling and viewport."""
        flow = self._create_flow("https://old.reddit.com/r/technology", method="GET")
        flow.response = MagicMock(spec=http.Response)
        flow.response.headers = {"Content-Type": "text/html; charset=UTF-8"}
        flow.response.text = '<html><head><meta name="viewport" content="width=1024"></head><body></body></html>'

        result = self.proxy.response(flow)

        self.assertTrue(result)
        self.assertIn('<meta name="viewport" content="width=device-width,initial-scale=1.0">', flow.response.text)
        self.assertIn('id="legacy-proxy-mobile"', flow.response.text)

if __name__ == "__main__":
    unittest.main()
