import plistlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.services.icloud import ICloudProxy
from src.services.icloud_gsa import ICloudCredentials


class ICloudProxyTests(unittest.TestCase):
    def _flow(self, url, method="POST", body=b"legacy-body", status=200):
        request = SimpleNamespace(method=method, url=url, headers={"Authorization": "Bearer old", "X-Mme-Nas-Qualify": "qualify"}, raw_content=body)
        response = SimpleNamespace(status_code=status, headers={}, raw_content=b"")
        return SimpleNamespace(request=request, response=response)

    def _proxy(self):
        proxy = ICloudProxy()
        proxy.credentials = ICloudCredentials("user@example.test", "pet-value", "adsid-value", "dsid", "mme", {"status": 0, "service-data": {"tokens": {"mmeAuthToken": "mme"}}})
        proxy.gsa = SimpleNamespace(provider=SimpleNamespace(headers=lambda session: {"X-Apple-I-MD": "md"}), session=object())
        return proxy

    def test_login_returns_synthesized_legacy_response(self):
        flow = self._flow("https://setup.icloud.com/setup/login_or_create_account")
        proxy = self._proxy()
        proxy.request(flow)
        payload = plistlib.loads(flow.response.content)
        self.assertEqual(flow.response.status_code, 200)
        self.assertEqual(payload["status"], 0)
        self.assertEqual(payload["protocolVersion"], "2")
        self.assertEqual(payload["dsid"], "dsid")
        self.assertEqual(payload["delegates"]["com.apple.mobileme"]["status"], 0)

    def test_delegates_preserves_body_and_adds_anisette(self):
        flow = self._flow("https://setup.icloud.com/setup/iosbuddy/loginDelegates")
        self._proxy().request(flow)
        self.assertEqual(flow.request.raw_content, b"legacy-body")
        self.assertEqual(flow.request.headers["X-Apple-I-MD"], "md")

    def test_request_logs_synthesis(self):
        flow = self._flow("https://setup.icloud.com/setup/login_or_create_account")
        with patch("builtins.print") as output:
            self._proxy().request(flow)
        log = "\n".join(call.args[0] for call in output.call_args_list)
        self.assertIn("[ICLOUD] synthesized login_or_create_account success response", log)

    def test_ignores_other_endpoints(self):
        flow = self._flow("https://setup.icloud.com/setup/qualify/session", method="GET")
        with patch("builtins.print") as output:
            self._proxy().request(flow)
            self._proxy().response(flow)
        log = "\n".join(call.args[0] for call in output.call_args_list)
        self.assertIn("[ICLOUD TRACE] GET /setup/qualify/session -> <pending>", log)
        self.assertIn("[ICLOUD TRACE] GET /setup/qualify/session -> 200", log)
        self.assertNotIn("Authorization", log)
        self.assertNotIn("legacy-body", log)

    def test_trace_does_not_log_query_or_sensitive_headers(self):
        flow = self._flow(
            "https://setup.icloud.com/setup/next?token=secret",
            body=b"password=secret",
        )
        with patch("builtins.print") as output:
            self._proxy().request(flow)
            self._proxy().response(flow)
        log = "\n".join(call.args[0] for call in output.call_args_list)
        self.assertNotIn("?token=secret", log)
        self.assertNotIn("secret", log)


if __name__ == "__main__":
    unittest.main()
