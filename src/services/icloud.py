import base64
import plistlib
from urllib.parse import urlsplit

from mitmproxy import http
from src.services.icloud_gsa import ICloudGSA

ICLOUD_HOST = "setup.icloud.com"
LOGIN_PATH = "/setup/login_or_create_account"
DELEGATES_PATH = "/setup/iosbuddy/loginDelegates"


class ICloudProxy:
    def __init__(self):
        self.credentials = None
        self.gsa = None

    def authenticate(self):
        print("[ICLOUD] authenticating...")
        self.gsa = ICloudGSA(on_two_factor=lambda: print("[ICLOUD] 2FA required"))
        apple_id = input("Apple ID: ").strip()
        from getpass import getpass
        password = getpass("Password: ")
        try:
            self.credentials = self.gsa.authenticate(apple_id, password)
            print("[ICLOUD] GSA authentication successful")
            response, _ = self.gsa.login_delegates(self.credentials)
            print(f"[ICLOUD] loginDelegates status={response.status_code}")
            if not (self.credentials.dsid and self.credentials.mme_auth_token):
                raise RuntimeError("loginDelegates identity unavailable")
            print("[ICLOUD] iCloud credentials ready")
        finally:
            password = ""

    @staticmethod
    def _target(flow, path):
        parts = urlsplit(flow.request.url)
        return (parts.hostname or "").lower().rstrip(".") == ICLOUD_HOST and parts.path == path

    def _set_auth(self, flow):
        credentials = self.credentials
        encoded = base64.b64encode(f"{credentials.apple_id}:{credentials.pet}".encode()).decode("ascii")
        flow.request.headers["Authorization"] = "Basic " + encoded
        flow.request.headers["X-Apple-ADSID"] = credentials.adsid

    @staticmethod
    def _is_setup(flow):
        parts = urlsplit(flow.request.url)
        return (parts.hostname or "").lower().rstrip(".") == ICLOUD_HOST

    @staticmethod
    def _trace_request(flow):
        parts = urlsplit(flow.request.url)
        print(
            f"[ICLOUD TRACE] {flow.request.method} {parts.path or '/'} -> <pending> "
            f"User-Agent={flow.request.headers.get('User-Agent', '<none>')} "
            f"X-MMe-Client-Info={flow.request.headers.get('X-MMe-Client-Info', '<none>')}"
        )

    @staticmethod
    def _trace_response(flow):
        parts = urlsplit(flow.request.url)
        print(
            f"[ICLOUD TRACE] {flow.request.method} {parts.path or '/'} -> {flow.response.status_code} "
            f"User-Agent={flow.request.headers.get('User-Agent', '<none>')} "
            f"X-MMe-Client-Info={flow.request.headers.get('X-MMe-Client-Info', '<none>')}"
        )

    def _legacy_login_response(self):
        credentials = self.credentials
        if not credentials or not credentials.dsid or not credentials.mme_auth_token or not credentials.mobileme_delegate:
            return None
        body = plistlib.dumps({
            "dsid": credentials.dsid,
            "delegates": {"com.apple.mobileme": credentials.mobileme_delegate},
            "protocolVersion": "2",
            "status": 0,
        })
        print("[ICLOUD] synthesized login_or_create_account success response")
        print("[ICLOUD] legacy response keys=['delegates', 'dsid', 'protocolVersion', 'status']")
        return http.Response.make(200, body, {"Content-Type": "application/xml; charset=UTF-8"})

    def request(self, flow):
        if self._is_setup(flow):
            self._trace_request(flow)
        if not self.credentials:
            return
        if self._target(flow, LOGIN_PATH):
            response = self._legacy_login_response()
            if response is not None:
                flow.response = response
                return
        if self._target(flow, DELEGATES_PATH):
            self._set_auth(flow)
            for name, value in self.gsa.provider.headers(self.gsa.session).items():
                flow.request.headers[name] = value

    def response(self, flow):
        if self._is_setup(flow):
            self._trace_response(flow)
        if self._target(flow, DELEGATES_PATH):
            print(f"[ICLOUD] loginDelegates status={flow.response.status_code}")
