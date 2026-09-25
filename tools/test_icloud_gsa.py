#!/usr/bin/env python3
"""Standalone GSA/PET/loginDelegates probe using the proxy's GSA helper."""

import json
import sys

try:
    from src.services.icloud_gsa import ICloudGSA, GSAError
except RuntimeError as error:
    raise SystemExit(str(error)) from error


def _partial(value):
    if not value:
        return "[missing]"
    return value[:4] + "..." + value[-4:] if len(value) > 8 else "[redacted]"


def _find(value, name):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() == name.lower() and not isinstance(item, (dict, list)):
                return item
            found = _find(item, name)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find(item, name)
            if found is not None:
                return found
    return None


def main():
    apple_id = input("Apple ID: ").strip()
    from getpass import getpass
    password = getpass("Password: ")
    try:
        client = ICloudGSA(on_two_factor=lambda: print("2FA required"))
        credentials = client.authenticate(apple_id, password)
        response, payload = client.login_delegates(credentials)
    except (GSAError, OSError, ValueError) as error:
        print(f"GSA authenticated correctly: no ({type(error).__name__})")
        return 1
    finally:
        password = ""

    print("GSA authenticated correctly: yes")
    print("PET obtained: yes")
    print(f"PET length: {len(credentials.pet)}")
    print(f"ADSID: {_partial(credentials.adsid)}")
    print(f"loginDelegates HTTP status: {response.status_code}")
    print(f"loginDelegates internal status: {_find(payload, 'status')}")
    print(f"loginDelegates status-message: {json.dumps(_find(payload, 'status-message'))}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        raise SystemExit(1)
