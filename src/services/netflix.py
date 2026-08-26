import json
import time
import urllib.parse
from mitmproxy import http

NETFLIX_API_HOSTS = {
    "api-global.netflix.com",
    "api.netflix.com",
    "ios.prod.ftl.netflix.com",
    "prod.ftl.netflix.com",
    "secure.netflix.com",
    "www.netflix.com",
    "netflix.com",
}

NETFLIX_TELEMETRY_HOSTS = {
    "ichnaea.netflix.com",
    "customerevents.netflix.com",
    "presentation.netflix.com",
    "logs.netflix.com",
    "tracking.netflix.com",
    "beacon.netflix.com",
}

NETFLIX_ALL_HOSTS = NETFLIX_API_HOSTS | NETFLIX_TELEMETRY_HOSTS | {
    "assets.nflxext.com",
    "codex.nflxext.com",
    "nflximg.net",
    "nflxvideo.net",
    "nflxso.net",
}


class NetflixProxy:
    def __init__(self, config=None):
        self.config = config

    def _matches_host(self, host: str, host_set: set) -> bool:
        host = host.lower().rstrip(".")
        return host in host_set or any(host.endswith("." + h) for h in host_set)

    def _parse_paths(self, flow) -> list:
        parsed_url = urllib.parse.urlparse(flow.request.url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        paths = []

        #parse 'path' query parameters (e.g., path=["config"]&path=["geolocation"])
        for p in query_params.get("path",[]):
            try:
                loaded = json.loads(p)
                paths.append(loaded if isinstance(loaded,list) else [loaded])
            except Exception:
                paths.append([p])

        #parse 'paths' query parameters
        for p in query_params.get("paths",[]):
            try:
                loaded = json.loads(p)
                if isinstance(loaded,list):
                    if loaded and isinstance(loaded[0],list):
                        paths.extend(loaded)
                    else:
                        paths.append(loaded)
                else:
                    paths.append([loaded])
            except Exception:
                paths.append([p])

        #parse POST JSON body if available
        if flow.request.raw_content:
            try:
                body_json = json.loads(flow.request.raw_content.decode("utf-8",errors="replace"))
                if isinstance(body_json, dict):
                    if "paths" in body_json and isinstance(body_json["paths"],list):
                        for p in body_json["paths"]:
                            paths.append(p if isinstance(p,list) else [p])
                    if "path" in body_json:
                        p = body_json["path"]
                        paths.append(p if isinstance(p,list) else [p])
                    if "callPath" in body_json:
                        p = body_json["callPath"]
                        paths.append(p if isinstance(p,list) else [p])
            except Exception:
                pass

        return paths

    def _build_jsongraph_response(self,requested_paths: list,query_params: dict) -> dict:
        json_graph = {}
        resolved_paths = []

        #fallback default paths if none provided
        if not requested_paths:
            requested_paths = [
                ["customerSupportVoipAuthorizations"],
                ["geolocation"],
                ["languages"],
                ["config"],
            ]

        locale = query_params.get("locale",["es"])[0]
        country_code = locale[:2].upper() if len(locale) >= 2 else "ES"
        languages_param = query_params.get("languages",["es"])[0]

        for path_tokens in requested_paths:
            if not isinstance(path_tokens, list):
                path_tokens = [path_tokens]

            resolved_paths.append(path_tokens)
            root_key = str(path_tokens[0]) if path_tokens else ""

            if root_key == "customerSupportVoipAuthorizations":
                json_graph["customerSupportVoipAuthorizations"] = {
                    "$type": "atom",
                    "value": {
                        "isAuthorized": True,
                        "isVoipEnabled": False,
                        "canMakeVoipCalls": False,
                        "status": "success",
                    },
                }
            elif root_key == "geolocation":
                json_graph["geolocation"] = {
                    "$type": "atom",
                    "value": {
                        "country": country_code,
                        "countryCode": country_code,
                        "region": country_code,
                        "ip": "127.0.0.1",
                        "isNetflixCountry": True,
                        "status": "success",
                    },
                }
            elif root_key == "languages":
                json_graph["languages"] = {
                    "$type": "atom",
                    "value": [
                        languages_param,
                        f"{languages_param.lower()}-{country_code}",
                        "es-ES",
                        "es",
                        "en-US",
                        "en",
                    ],
                }
            elif root_key == "config":
                json_graph["config"] = {
                    "$type": "atom",
                    "value": {
                        "showSignIn": True,
                        "showSignUp": True,
                        "enableSignIn": True,
                        "enableSignUp": True,
                        "enableVoip": False,
                        "isVoipEnabled": False,
                        "voip": {
                            "enabled": False,
                        },
                        "deviceConfig": {
                            "enableVoip": False,
                            "enableSignIn": True,
                            "enableSignUp": True,
                            "isVoipEnabled": False,
                        },
                        "customerSupport": {
                            "isVoipEnabled": False,
                            "supportPhoneNumber": "",
                            "supportUrl": "https://help.netflix.com",
                        },
                        "streamingConfig": {
                            "enableSsl": True,
                        },
                        "alert": None,
                        "forceUpdate": False,
                        "maintenance": False,
                    },
                }
            else:
                #generic fallback for unknown paths (e.g. user, genres, profiles, etc.)
                if len(path_tokens) == 1:
                    json_graph[root_key] = {
                        "$type": "atom",
                        "value": {},
                    }
                else:
                    curr = json_graph
                    for token in path_tokens[:-1]:
                        token_str = str(token)
                        if token_str not in curr:
                            curr[token_str] = {}
                        curr = curr[token_str]
                    curr[str(path_tokens[-1])] = {
                        "$type": "atom",
                        "value": {},
                    }
                print(f"[INFO] Netflix Falcor unhandled path: {path_tokens}")

        return {
            "jsonGraph": json_graph,
            "paths": resolved_paths,
        }

    def request(self,flow) -> bool:
        host = flow.request.pretty_host.lower()
        path = flow.request.path.split("?", 1)[0]
        parsed_url = urllib.parse.urlparse(flow.request.url)
        query_params = urllib.parse.parse_qs(parsed_url.query)

        #telemetry and Logging intercept
        if self._matches_host(host, NETFLIX_TELEMETRY_HOSTS) or path in {
            "/log",
            "/event",
            "/events",
            "/beacon",
            "/metrics",
            "/ichnaea",
        } or path.startswith(("/cadmium/log", "/ichnaea")):
            flow.response = http.Response.make(
                200,
                b'{"status":"ok","success":true}',
                {
                    "Content-Type": "application/json; charset=utf-8",
                    "Cache-Control": "no-store",
                },
            )
            return True

        #appboot and device config endpoints
        if self._matches_host(host, NETFLIX_API_HOSTS):
            if path.startswith(("/appboot", "/deviceConfig", "/android/samurai/config")):
                appboot_data = json.dumps(
                    {
                        "status": "ok",
                        "appboot": {
                            "isSupported": True,
                            "minAppVersion": "8.0.0",
                            "currentAppVersion": "8.0.2",
                            "serverTime": int(time.time()),
                        },
                    }
                ).encode("utf-8")
                flow.response = http.Response.make(
                    200,
                    appboot_data,
                    {
                        "Content-Type": "application/json; charset=utf-8",
                        "Cache-Control": "no-store",
                    },
                )
                return True

            #falcor JSONGraph API (iosui/user, pathEvaluator, router, falcor)
            if path.startswith(("/iosui/user", "/iosui", "/pathEvaluator", "/falcor", "/router")):
                requested_paths = self._parse_paths(flow)
                response_data = self._build_jsongraph_response(requested_paths, query_params)
                resp_bytes = json.dumps(response_data).encode("utf-8")
                flow.response = http.Response.make(
                    200,
                    resp_bytes,
                    {
                        "Content-Type": "application/json; charset=utf-8",
                        "Content-Length": str(len(resp_bytes)),
                        "Cache-Control": "no-store, no-cache, must-revalidate",
                        "Pragma": "no-cache",
                    },
                )
                print(f"[INFO] Intercepted Netflix JSONGraph request: {flow.request.url} -> {list(response_data['jsonGraph'].keys())}")
                return True

        return False

    def response(self,flow):
        host = flow.request.pretty_host.lower()
        if self._matches_host(host, NETFLIX_ALL_HOSTS):
            if flow.response and flow.response.status_code >= 400:
                print(f"[WARN] Netflix upstream {flow.request.url} returned {flow.response.status_code}")

    def error(self,flow) -> bool:
        host = (flow.request.pretty_host if flow.request else "").lower()
        if self._matches_host(host,NETFLIX_ALL_HOSTS) or "netflix.com" in host or "nflx" in host:
            print(f"[INFO] Handling Netflix error gracefully for {host}")
            flow.response = http.Response.make(
                200,
                b'{"status":"ok"}',
                {
                    "Content-Type": "application/json; charset=utf-8",
                    "Cache-Control": "no-store",
                },
            )
            return True
        return False