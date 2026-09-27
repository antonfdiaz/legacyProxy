import unittest
from types import SimpleNamespace
from src.services.google_earth import (
    GoogleEarthProxy,
    GOOGLE_EARTH_USER_AGENT,
    is_google_earth_host,
    is_google_earth_request,
)

class TestGoogleEarthProxy(unittest.TestCase):
    def setUp(self):
        self.proxy = GoogleEarthProxy()

    def test_is_google_earth_host(self):
        self.assertTrue(is_google_earth_host("kh.google.com"))
        self.assertTrue(is_google_earth_host("khm.google.com"))
        self.assertTrue(is_google_earth_host("khm0.google.com"))
        self.assertTrue(is_google_earth_host("khm3.google.com"))
        self.assertTrue(is_google_earth_host("auth.keyhole.com"))
        self.assertTrue(is_google_earth_host("keyhole.com"))
        
        self.assertFalse(is_google_earth_host("google.com"))
        self.assertFalse(is_google_earth_host("www.google.com"))
        self.assertFalse(is_google_earth_host("example.com"))

    def test_is_google_earth_request_by_user_agent(self):
        flow = SimpleNamespace(
            request=SimpleNamespace(
                pretty_host="maps.google.com",
                headers={"User-Agent": "GoogleEarth/7.1.1 (iOS; iPhone)"},
            )
        )
        self.assertTrue(is_google_earth_request(flow))

        flow2 = SimpleNamespace(
            request=SimpleNamespace(
                pretty_host="example.com",
                headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 6_1_3 like Mac OS X) AppleWebKit/536.26"},
            )
        )
        self.assertFalse(is_google_earth_request(flow2))

    def test_spoofs_user_agent_for_kh_google_com(self):
        headers = {"User-Agent": "GoogleEarth/7.1.1 (iOS; iPhone)"}
        flow = SimpleNamespace(
            request=SimpleNamespace(
                pretty_host="kh.google.com",
                headers=headers,
                path="/dbRoot.v5",
                url="http://kh.google.com/dbRoot.v5",
            )
        )
        handled = self.proxy.request(flow)
        self.assertTrue(handled)
        self.assertEqual(flow.request.headers["User-Agent"], GOOGLE_EARTH_USER_AGENT)

    def test_strip_embedded_param_dbroot(self):
        # type=embedded at the end
        url1 = "http://kh.google.com/dbRoot.v5?hl=en&gl=us&type=embedded"
        self.assertEqual(
            self.proxy.strip_embedded_param(url1),
            "http://kh.google.com/dbRoot.v5?hl=en&gl=us",
        )

        # type=embedded at the beginning
        url2 = "http://kh.google.com/dbRoot.v5?type=embedded&hl=en&gl=us"
        self.assertEqual(
            self.proxy.strip_embedded_param(url2),
            "http://kh.google.com/dbRoot.v5?hl=en&gl=us",
        )

        # type=embedded alone
        url3 = "http://kh.google.com/dbRoot.v5?type=embedded"
        self.assertEqual(
            self.proxy.strip_embedded_param(url3),
            "http://kh.google.com/dbRoot.v5",
        )

        # no type=embedded
        url4 = "http://kh.google.com/dbRoot.v5?hl=en&gl=us"
        self.assertEqual(
            self.proxy.strip_embedded_param(url4),
            "http://kh.google.com/dbRoot.v5?hl=en&gl=us",
        )

    def test_request_rewrites_dbroot_url(self):
        headers = {"User-Agent": "GoogleEarth/7.1.1 (iOS; iPhone)"}
        flow = SimpleNamespace(
            request=SimpleNamespace(
                pretty_host="kh.google.com",
                headers=headers,
                path="/dbRoot.v5?hl=en&type=embedded",
                url="http://kh.google.com/dbRoot.v5?hl=en&type=embedded",
            )
        )
        handled = self.proxy.request(flow)
        self.assertTrue(handled)
        self.assertEqual(flow.request.headers["User-Agent"], GOOGLE_EARTH_USER_AGENT)
        self.assertEqual(flow.request.url, "http://kh.google.com/dbRoot.v5?hl=en")

    def test_ignores_non_google_earth_requests(self):
        headers = {"User-Agent": "Mozilla/5.0"}
        flow = SimpleNamespace(
            request=SimpleNamespace(
                pretty_host="wikipedia.org",
                headers=headers,
                path="/wiki/Main_Page",
                url="https://wikipedia.org/wiki/Main_Page",
            )
        )
        handled = self.proxy.request(flow)
        self.assertFalse(handled)
        self.assertEqual(flow.request.headers["User-Agent"], "Mozilla/5.0")

if __name__ == "__main__":
    unittest.main()
