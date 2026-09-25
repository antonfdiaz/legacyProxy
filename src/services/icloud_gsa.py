import base64
import hashlib
import hmac
import os
import plistlib
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from getpass import getpass

try:
    import truststore
    if sys.platform == "darwin":
        truststore.inject_into_ssl()
    import requests
    import srp
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError as error:
    raise RuntimeError("Install tools/requirements_icloud_gsa.txt") from error

GSA_URL = "https://gsa.apple.com/grandslam/GsService2"
TRUSTED_DEVICE_URL = "https://gsa.apple.com/auth/verify/trusteddevice"
VALIDATE_URL = "https://gsa.apple.com/grandslam/GsService2/validate"
LOGIN_DELEGATES_URL = "https://setup.icloud.com/setup/iosbuddy/loginDelegates"
CLIENT_INFO = "<MacBookPro18,3> <Mac OS X;13.4.1;22F8> <com.apple.AOSKit/282 (com.apple.accountsd/113)>"
PLIST_HEADER = b"""<?xml version='1.0' encoding='UTF-8'?>
<!DOCTYPE plist PUBLIC '-//Apple//DTD PLIST 1.0//EN' 'http://www.apple.com/DTDs/PropertyList-1.0.dtd'>
"""

srp.rfc5054_enable()
srp.no_username_in_x()


class GSAError(Exception):
    pass


@dataclass
class ICloudCredentials:
    apple_id: str
    pet: str
    adsid: str
    dsid: str = ""
    mme_auth_token: str = ""
    mobileme_delegate: dict = field(default_factory=dict)


def _text(value):
    return base64.b64encode(value).decode("ascii") if isinstance(value, bytes) else str(value)


def _find_scalar(value, names):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in names and not isinstance(item, (dict, list, tuple)):
                return str(key), item
            found = _find_scalar(item, names)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_scalar(item, names)
            if found:
                return found
    return None


class AnisetteProvider:
    def __init__(self, url=None):
        self.url = url or os.environ.get("ICLOUD_ANISETTE_URL", "http://localhost:6969")
        self.user_id = uuid.uuid4()
        self.device_id = uuid.uuid4()

    def headers(self, session):
        response = session.get(self.url, timeout=10)
        response.raise_for_status()
        values = response.json()
        if not values.get("X-Apple-I-MD") or not values.get("X-Apple-I-MD-M"):
            raise GSAError("anisette headers unavailable")
        locale = (os.environ.get("LC_ALL") or os.environ.get("LANG") or "en_US").split(".", 1)[0].replace("-", "_")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        return {
            "X-Apple-I-MD": values["X-Apple-I-MD"],
            "X-Apple-I-MD-M": values["X-Apple-I-MD-M"],
            "X-Apple-I-Client-Time": now.isoformat().replace("+00:00", "Z"),
            "X-Apple-I-TimeZone": "UTC",
            "loc": locale,
            "X-Apple-Locale": locale,
            "X-Apple-I-MD-RINFO": "17106176",
            "X-Apple-I-MD-LU": base64.b64encode(str(self.user_id).upper().encode()).decode(),
            "X-Mme-Device-Id": str(self.device_id).upper(),
            "X-Apple-I-SRL-NO": "0",
        }


class ICloudGSA:
    def __init__(self, anisette_url=None, session=None, on_two_factor=None):
        self.session = session or requests.Session()
        self.session.trust_env = False
        self.provider = AnisetteProvider(anisette_url)
        self.on_two_factor = on_two_factor

    def _headers(self):
        headers = {
            "Content-Type": "text/x-xml-plist",
            "Accept": "*/*",
            "User-Agent": "akd/1.0 CFNetwork/978.0.7 Darwin/18.7.0",
            "X-MMe-Client-Info": CLIENT_INFO,
        }
        headers.update(self.provider.headers(self.session))
        return headers

    def _request(self, parameters):
        request = {"cpd": {"bootstrap": True, "icscrec": True, "pbe": False, "prkgen": True, "svct": "iCloud"}}
        request.update(parameters)
        envelope = {"Header": {"Version": "1.0.1"}, "Request": request}
        response = self.session.post(GSA_URL, headers=self._headers(), data=plistlib.dumps(envelope), timeout=20)
        response.raise_for_status()
        payload = plistlib.loads(response.content).get("Response")
        if not isinstance(payload, dict):
            raise GSAError("invalid GSA response")
        status = payload.get("Status")
        status = status if isinstance(status, dict) else payload
        if status.get("ec") not in (None, 0, "0"):
            raise GSAError("GSA rejected authentication")
        return payload

    @staticmethod
    def _derive_password(password, salt, iterations):
        digest = hashlib.sha256(password.encode()).digest()
        return hashlib.pbkdf2_hmac("sha256", digest, salt, iterations, 32)

    @staticmethod
    def _decrypt_spd(user, encrypted):
        key_material = user.get_session_key()
        key = hmac.new(key_material, b"extra data key:", hashlib.sha256).digest()
        iv = hmac.new(key_material, b"extra data iv:", hashlib.sha256).digest()[:16]
        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        padded = decryptor.update(encrypted) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        decrypted = unpadder.update(padded) + unpadder.finalize()
        try:
            return plistlib.loads(decrypted)
        except plistlib.InvalidFileException:
            return plistlib.loads(PLIST_HEADER + decrypted)

    @staticmethod
    def _two_factor_required(payload):
        status = payload.get("Status")
        return isinstance(status, dict) and status.get("au") in {"trustedDeviceSecondaryAuth", "secondaryAuth"}

    def _complete_two_factor(self, spd):
        adsid = _text(spd.get("adsid"))
        token = _text(spd.get("GsIdmsToken"))
        headers = self._headers()
        headers.update({
            "Accept": "text/x-xml-plist",
            "X-Apple-Identity-Token": base64.b64encode(f"{adsid}:{token}".encode()).decode(),
            "X-Apple-App-Info": "com.apple.gs.xcode.auth",
            "X-Xcode-Version": "11.2 (11B41)",
        })
        self.session.get(TRUSTED_DEVICE_URL, headers=headers, timeout=20).raise_for_status()
        code = getpass("Apple 2FA code: ").strip()
        headers["security-code"] = code
        self.session.get(VALIDATE_URL, headers=headers, timeout=20).raise_for_status()

    def authenticate(self, apple_id, password, allow_two_factor=True):
        user = srp.User(apple_id, b"", hash_alg=srp.SHA256, ng_type=srp.NG_2048)
        _, public_a = user.start_authentication()
        init = self._request({"A2k": public_a, "ps": ["s2k", "s2k_fo"], "u": apple_id, "o": "init"})
        if init.get("sp") != "s2k":
            raise GSAError("unsupported GSA password scheme")
        user.p = self._derive_password(password, init["s"], init["i"])
        proof = user.process_challenge(init["s"], init["B"])
        if proof is None:
            raise GSAError("GSA challenge failed")
        complete = self._request({"c": init["c"], "M1": proof, "u": apple_id, "o": "complete"})
        user.verify_session(complete["M2"])
        if not user.authenticated():
            raise GSAError("GSA session verification failed")
        spd = self._decrypt_spd(user, complete["spd"])
        if self._two_factor_required(complete):
            if not allow_two_factor:
                raise GSAError("second-factor retry failed")
            if self.on_two_factor:
                self.on_two_factor()
            self._complete_two_factor(spd)
            return self.authenticate(apple_id, password, False)
        tokens = spd.get("t") if isinstance(spd.get("t"), dict) else {}
        pet_entry = tokens.get("com.apple.gs.idms.pet") or {}
        pet = _text(pet_entry.get("token")) if pet_entry.get("token") else ""
        adsid = _text(spd.get("adsid")) if spd.get("adsid") else ""
        if not pet or not adsid:
            raise GSAError("PET or ADSID missing")
        return ICloudCredentials(apple_id, pet, adsid)

    def login_delegates(self, credentials, body=None):
        if body is None:
            body = plistlib.dumps({
                "apple-id": credentials.apple_id,
                "delegates": {"com.apple.mobileme": {}},
                "password": credentials.pet,
                "client-id": str(self.provider.user_id),
            })
        headers = {"X-Apple-ADSID": credentials.adsid, "X-Mme-Client-Info": CLIENT_INFO}
        headers.update(self.provider.headers(self.session))
        response = self.session.post(LOGIN_DELEGATES_URL, auth=(credentials.apple_id, credentials.pet), headers=headers, data=body, timeout=20)
        payload = {}
        try:
            payload = plistlib.loads(response.content)
        except (plistlib.InvalidFileException, ValueError):
            try:
                payload = response.json()
            except ValueError:
                pass
        if not isinstance(payload, dict):
            payload = {}
        dsid = _find_scalar(payload, {"dsid"})
        mme = _find_scalar(payload, {"mmeauthtoken", "mme-auth-token", "mme_auth_token"})
        credentials.dsid = _text(dsid[1]) if dsid else ""
        credentials.mme_auth_token = _text(mme[1]) if mme else ""
        delegates = payload.get("delegates")
        if isinstance(delegates, dict) and isinstance(delegates.get("com.apple.mobileme"), dict):
            credentials.mobileme_delegate = delegates["com.apple.mobileme"]
        return response, payload
