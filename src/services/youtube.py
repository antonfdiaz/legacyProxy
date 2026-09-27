import asyncio
import json
import ssl
import urllib.parse
import urllib.request
from typing import Optional, Dict, Any, Union
from mitmproxy import http

YOUTUBE_API_KEY = "AIzaSyB-63vPrdThhKuerbB2N_l7Kwwcxj6yUAc"
INNERTUBE_BASE_URL = "https://www.googleapis.com/youtubei/v1"

YOUTUBE_HOSTS = {
    "googleapis.com",
    "www.googleapis.com",
    "youtubei.googleapis.com",
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "i.ytimg.com",
    "ytimg.com",
    "googlevideo.com",
}

def is_youtube_request(flow) -> bool:
    request = getattr(flow, "request", None)
    if not request:
        return False
    host = (getattr(request, "pretty_host", "") or "").lower().rstrip(".")
    path = getattr(request, "path", "").lower()
    user_agent = request.headers.get("User-Agent", "").lower()

    if "com.google.ios.youtube" in user_agent or "youtube/" in user_agent:
        return True
    if "youtubei/v1" in path:
        return True
    if host in {"youtubei.googleapis.com"}:
        return True
    if ("googleapis.com" in host or "youtube.com" in host) and "youtubei" in path:
        return True
    return False

def extract_proto_fields(data: bytes) -> dict:
    """Lightweight wire-format parser to extract top-level Protobuf fields."""
    fields = {}
    i = 0
    while i < len(data):
        key = 0
        shift = 0
        while True:
            if i >= len(data):
                return fields
            b = data[i]
            i += 1
            key |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        f_num = key >> 3
        w_type = key & 7
        if w_type == 0:
            val = 0
            shift = 0
            while True:
                if i >= len(data):
                    return fields
                b = data[i]
                i += 1
                val |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            fields[f_num] = val
        elif w_type == 2:
            length = 0
            shift = 0
            while True:
                if i >= len(data):
                    return fields
                b = data[i]
                i += 1
                length |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            val = data[i : i + length]
            i += length
            fields[f_num] = val
        elif w_type == 1:
            i += 8
        elif w_type == 5:
            i += 4
        else:
            break
    return fields

def extract_proto_context(proto_bytes: bytes) -> tuple:
    """Extract (hl, gl) from Protobuf context Field 1."""
    try:
        f = extract_proto_fields(proto_bytes)
        ctx = f.get(1, b"")
        if isinstance(ctx, bytes):
            f_ctx = extract_proto_fields(ctx)
            client = f_ctx.get(1, b"")
            if isinstance(client, bytes):
                f_client = extract_proto_fields(client)
                hl = f_client.get(1, b"es").decode("utf-8", "ignore")
                gl = f_client.get(2, b"ES").decode("utf-8", "ignore")
                return hl, gl
    except Exception:
        pass
    return "es", "ES"

def filter_proto(data: bytes, drop_fields={777}) -> bytes:
    """Strip unsupported/modern protobuf fields (like Field 777 frameworkUpdates / Elements)."""
    out = bytearray()
    i = 0
    while i < len(data):
        start = i
        key = 0
        shift = 0
        while True:
            if i >= len(data):
                break
            b = data[i]
            i += 1
            key |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        if i >= len(data):
            break
        f_num = key >> 3
        w_type = key & 7
        if w_type == 0:
            while data[i] & 0x80:
                i += 1
            i += 1
            if f_num not in drop_fields:
                out.extend(data[start:i])
        elif w_type == 2:
            length = 0
            shift = 0
            while True:
                b = data[i]
                i += 1
                length |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            i += length
            if f_num not in drop_fields:
                out.extend(data[start:i])
        elif w_type == 1:
            i += 8
            if f_num not in drop_fields:
                out.extend(data[start:i])
        elif w_type == 5:
            i += 4
            if f_num not in drop_fields:
                out.extend(data[start:i])
        else:
            break
    return bytes(out)

def make_empty_browse_response(browse_id: str) -> dict:
    """Fallback empty browse response to prevent legacy app crashes."""
    title_text = "Inicio" if browse_id in {"FEwhat_to_watch", "FEtrending"} else "YouTube"
    return {
        "responseContext": {},
        "contents": {
            "singleColumnBrowseResultsRenderer": {
                "tabs": [
                    {
                        "tabRenderer": {
                            "selected": True,
                            "tabIdentifier": browse_id,
                            "title": {"runs": [{"text": title_text}]},
                            "content": {
                                "sectionListRenderer": {
                                    "contents": [
                                        {
                                            "itemSectionRenderer": {
                                                "contents": []
                                            }
                                        }
                                    ]
                                }
                            },
                        }
                    }
                ]
            }
        },
    }

SAFE_ANTI_UPGRADE_PROTO = bytes.fromhex(
    "0a00"  # Field 1 (responseContext): length 0
    "1a2c"  # Field 3 (globalConfig): length 44 (0x2c)
    "fae3dbf00112"  # Field 63102527 (upgradeConfig): length 18 (0x12)
    "080010002205312e302e302a05312e302e30"  # prompt=0, force=0, promptBelow="1.0.0", forceBelow="1.0.0"
    "e2f0c4a9030e"  # Field 111552268 (verboseUpgradeConfig): length 14 (0x0e)
    "0a05312e302e301205312e302e30"  # promptBelow="1.0.0", forceBelow="1.0.0"
)

SAFE_ANTI_UPGRADE_JSON = {
    "responseContext": {},
    "globalConfig": {
        "upgradeConfig": {
            "prompt": False,
            "force": False,
            "promptBelowVersion": "1.0.0",
            "forceBelowVersion": "1.0.0",
        },
        "verboseUpgradeConfig": {
            "promptBelowVersion": "1.0.0",
            "forceBelowVersion": "1.0.0",
        },
    },
}

def encode_varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)

def encode_field(f_num: int, w_type: int, val: Union[int, bytes]) -> bytes:
    tag = encode_varint((f_num << 3) | w_type)
    if w_type == 0:
        return tag + encode_varint(val)
    elif w_type == 2:
        return tag + encode_varint(len(val)) + val
    raise NotImplementedError(f"Unsupported wire type {w_type}")

def patch_proto_upgrade_config(data: bytes) -> bytes:
    """Neutralize forced upgrade fields in Protobuf config response."""
    try:
        top = extract_proto_fields(data)
        upgrade_cfg = bytes.fromhex("080010002205312e302e302a05312e302e30")
        verbose_cfg = bytes.fromhex("0a05312e302e301205312e302e30")
        
        if 3 not in top:
            field_63 = encode_field(63102527, 2, upgrade_cfg)
            field_111 = encode_field(111552268, 2, verbose_cfg)
            top[3] = field_63 + field_111
        else:
            f3 = extract_proto_fields(top[3])
            f3[63102527] = upgrade_cfg
            f3[111552268] = verbose_cfg
            new_f3 = bytearray()
            for k, v in f3.items():
                if isinstance(v, int):
                    new_f3.extend(encode_field(k, 0, v))
                elif isinstance(v, bytes):
                    new_f3.extend(encode_field(k, 2, v))
            top[3] = bytes(new_f3)
            
        new_top = bytearray()
        for k, v in top.items():
            if isinstance(v, int):
                new_top.extend(encode_field(k, 0, v))
            elif isinstance(v, bytes):
                new_top.extend(encode_field(k, 2, v))
        return filter_proto(bytes(new_top), drop_fields={777})
    except Exception as e:
        print(f"[WARN] YouTube: failed to patch proto upgrade config, using safe fallback: {e}")
        return SAFE_ANTI_UPGRADE_PROTO

def patch_json_upgrade_config(data: dict) -> dict:
    """Neutralize forced upgrade fields in JSON config response."""
    if not isinstance(data, dict):
        return SAFE_ANTI_UPGRADE_JSON
    res = dict(data)
    global_cfg = dict(res.get("globalConfig", {}))
    global_cfg["upgradeConfig"] = {
        "prompt": False,
        "force": False,
        "promptBelowVersion": "1.0.0",
        "forceBelowVersion": "1.0.0",
    }
    global_cfg["verboseUpgradeConfig"] = {
        "promptBelowVersion": "1.0.0",
        "forceBelowVersion": "1.0.0",
    }
    res["globalConfig"] = global_cfg
    return res

def extract_channel_id_from_player_proto(data: bytes) -> Optional[str]:
    """Extract real channelId from Field 11 (videoDetails) -> Subfield 19."""
    try:
        fields = extract_proto_fields(data)
        vd_bytes = fields.get(11)
        if isinstance(vd_bytes, bytes):
            vd_fields = extract_proto_fields(vd_bytes)
            cid_bytes = vd_fields.get(19)
            if isinstance(cid_bytes, bytes):
                cid = cid_bytes.decode("utf-8", "ignore")
                if cid.startswith("UC") and len(cid) == 24:
                    return cid
    except Exception:
        pass
    return None

def make_channel_nav_endpoint(channel_id: str) -> bytes:
    """Build a Protobuf navigationEndpoint with a browseEndpoint pointing to channel_id."""
    be = encode_field(2, 2, channel_id.encode("utf-8"))
    nav = encode_field(48687626, 2, be)
    return encode_field(4, 2, nav)

def patch_next_proto(data: bytes, channel_id: str) -> bytes:
    """Inject channel navigationEndpoint into videoOwnerRenderer and update outer lengths."""
    if not channel_id:
        return data
    try:
        f4 = make_channel_nav_endpoint(channel_id)
        diff = len(f4)

        tag_vor = encode_varint((51779708 << 3) | 2)
        pos_vor = data.find(tag_vor)
        if pos_vor == -1:
            return data

        out = bytearray()
        i = 0
        while i < len(data):
            tag_start = i
            key = 0
            shift = 0
            while True:
                b = data[i]
                i += 1
                key |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            w_type = key & 7
            if w_type == 0:
                while data[i] & 0x80:
                    i += 1
                i += 1
                out.extend(data[tag_start:i])
            elif w_type == 2:
                len_start = i
                length = 0
                shift = 0
                while True:
                    b = data[i]
                    i += 1
                    length |= (b & 0x7F) << shift
                    if not (b & 0x80):
                        break
                    shift += 7
                len_end = i
                body_end = len_end + length

                if tag_start <= pos_vor and body_end >= pos_vor:
                    new_len = length + diff
                    out.extend(data[tag_start:len_start])
                    out.extend(encode_varint(new_len))
                    if tag_start == pos_vor:
                        out.extend(data[len_end:body_end])
                        out.extend(f4)
                        i = body_end
                    else:
                        continue
                else:
                    out.extend(data[tag_start:body_end])
                    i = body_end
            elif w_type == 1:
                i += 8
                out.extend(data[tag_start:i])
            elif w_type == 5:
                i += 4
                out.extend(data[tag_start:i])
            else:
                out.extend(data[tag_start:])
                break
        return bytes(out)
    except Exception as e:
        print(f"[WARN] YouTube: failed to patch next proto with channel nav: {e}")
        return data

class YouTubeProxy:
    """
    Proxy service to restore legacy YouTube app functionality (e.g. YouTube v11.19.7 on iOS 7).
    
    Translates and adapts requests to YouTube's Innertube API:
    - Bypasses 'Update available' (HTTP 400 Precondition Failed)
    - Dynamically detects Protobuf (application/x-protobuf) and returns native Protobuf via Google's alt=proto
    - Maps Home and Trending feeds to compatible classic renderers (compactVideoRenderer)
    - Bridges search results to classic sectionListRenderer
    - Delivers both HLS streams (.m3u8) and progressive MP4 formats (itag 18) for video playback
    - Stubs deprecated notification/registration endpoints
    - Guarantees crash-proof responses
    """
    def __init__(self, config=None):
        self.config = config
        self._ssl_ctx = ssl._create_unverified_context()
        self._channel_cache: Dict[str, str] = {}

    async def _fetch_innertube(
        self, endpoint: str, payload: dict, as_proto: bool = False, api_key: str = YOUTUBE_API_KEY
    ) -> Optional[Union[dict, bytes]]:
        url = f"{INNERTUBE_BASE_URL}/{endpoint}?key={api_key}"
        if as_proto:
            url += "&alt=proto"

        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
        )
        loop = asyncio.get_running_loop()

        def _do_request():
            try:
                with urllib.request.urlopen(req, timeout=12, context=self._ssl_ctx) as resp:
                    raw = resp.read()
                    if as_proto:
                        return raw
                    return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as e:
                err_body = e.read()
                print(f"[WARN] YouTube Innertube {endpoint} (proto={as_proto}) returned HTTP {e.code}: {err_body[:200]!r}")
                return None
            except Exception as e:
                print(f"[ERROR] YouTube Innertube {endpoint} fetch error: {e}")
                return None

        return await loop.run_in_executor(None, _do_request)

    async def handle_browse(self, flow, body: dict, proto_fields: dict, wants_proto: bool) -> bool:
        req_query = getattr(flow.request, "query", {}) or {}

        # Extract browse_id: from json body, protobuf fields (field 2), or query
        browse_id = ""
        if body:
            browse_id = body.get("browseId") or body.get("browse_id") or ""
        elif proto_fields:
            field2 = proto_fields.get(2, b"")
            if isinstance(field2, bytes):
                browse_id = field2.decode("utf-8", "ignore")

        if not browse_id:
            browse_id = req_query.get("browseId") or req_query.get("browse_id") or ""

        if not browse_id:
            browse_id = "FEwhat_to_watch"
            print(f"[INFO] YouTube: browseId omitted by client, defaulting to 'FEwhat_to_watch'")

        continuation = body.get("continuation") or req_query.get("continuation") or ""
        if not continuation and proto_fields:
            field4 = proto_fields.get(4, b"")
            if isinstance(field4, bytes):
                continuation = field4.decode("utf-8", "ignore")

        params = body.get("params") or req_query.get("params") or ""
        if not params and proto_fields:
            field3 = proto_fields.get(3, b"")
            if isinstance(field3, bytes):
                params = field3.decode("utf-8", "ignore")

        hl, gl = "es", "ES"
        if body:
            client_info = body.get("context", {}).get("client", {})
            hl = client_info.get("hl", "es")
            gl = client_info.get("gl", "ES")
        elif getattr(flow.request, "content", None):
            hl, gl = extract_proto_context(flow.request.content)

        print(f"[INFO] YouTube: handling browse request for browseId={browse_id!r}, params={params!r}, continuation={bool(continuation)}, proto={wants_proto}")

        target_browse_id = browse_id
        if browse_id == "FEtrending":
            target_browse_id = "FEwhat_to_watch"

        if target_browse_id == "FEwhat_to_watch":
            primary_client = "ANDROID_TESTSUITE"
            primary_version = "1.9"
        elif target_browse_id.startswith("UC"):
            primary_client = "MWEB"
            primary_version = "2.20240401.00.00"
        else:
            primary_client = "IOS"
            primary_version = "20.01.1"

        payload: Dict[str, Any] = {
            "context": {
                "client": {
                    "clientName": primary_client,
                    "clientVersion": primary_version,
                    "hl": hl,
                    "gl": gl,
                }
            },
            "browseId": target_browse_id,
        }
        if continuation:
            payload["continuation"] = continuation
        if params and target_browse_id != "FEwhat_to_watch":
            payload["params"] = params

        resp_data = await self._fetch_innertube("browse", payload, as_proto=wants_proto)

        if not resp_data:
            print(f"[INFO] YouTube: primary browse fetch failed for {target_browse_id}, attempting fallback")
            alt_client = "WEB" if target_browse_id.startswith("UC") else ("IOS" if primary_client == "ANDROID_TESTSUITE" else "ANDROID_TESTSUITE")
            alt_version = "2.20240401.00.00" if alt_client == "WEB" else ("20.01.1" if alt_client == "IOS" else "1.9")
            fallback_payload: Dict[str, Any] = {
                "context": {
                    "client": {
                        "clientName": alt_client,
                        "clientVersion": alt_version,
                        "hl": hl,
                        "gl": gl,
                    }
                },
                "browseId": target_browse_id,
            }
            if continuation:
                fallback_payload["continuation"] = continuation
            resp_data = await self._fetch_innertube("browse", fallback_payload, as_proto=wants_proto)

        if wants_proto and isinstance(resp_data, bytes):
            clean_proto = filter_proto(resp_data, drop_fields={777})
            flow.response = http.Response.make(
                200,
                clean_proto,
                {"Content-Type": "application/x-protobuf"},
            )
            print(f"[INFO] YouTube: successfully handled browse ({browse_id}) -> Clean Protobuf ({len(clean_proto)} bytes, stripped {len(resp_data) - len(clean_proto)} modern bytes)")
            return True

        if isinstance(resp_data, dict):
            # Ensure tab title is never null in JSON mode
            if "contents" in resp_data:
                single = resp_data["contents"].get("singleColumnBrowseResultsRenderer", {})
                for tab in single.get("tabs", []):
                    tr = tab.get("tabRenderer")
                    if tr:
                        if not tr.get("title"):
                            tr["title"] = {"runs": [{"text": "Inicio" if target_browse_id == "FEwhat_to_watch" else "YouTube"}]}
                        if not tr.get("tabIdentifier"):
                            tr["tabIdentifier"] = target_browse_id

            flow.response = http.Response.make(
                200,
                json.dumps(resp_data).encode("utf-8"),
                {"Content-Type": "application/json; charset=utf-8"},
            )
            print(f"[INFO] YouTube: successfully handled browse ({browse_id}) -> JSON HTTP 200")
            return True

        # Fallback to prevent crash
        if wants_proto:
            flow.response = http.Response.make(
                200,
                b"\x0a\x00",
                {"Content-Type": "application/x-protobuf"},
            )
        else:
            flow.response = http.Response.make(
                200,
                json.dumps(make_empty_browse_response(target_browse_id)).encode("utf-8"),
                {"Content-Type": "application/json; charset=utf-8"},
            )
        print(f"[WARN] YouTube: returned safe fallback for browse ({browse_id})")
        return True

    async def handle_search(self, flow, body: dict, proto_fields: dict, wants_proto: bool) -> bool:
        query = ""
        if body:
            query = body.get("query", "")
        elif proto_fields:
            field2 = proto_fields.get(2, b"")
            if isinstance(field2, bytes):
                query = field2.decode("utf-8", "ignore")

        hl, gl = "es", "ES"
        if body:
            client_info = body.get("context", {}).get("client", {})
            hl = client_info.get("hl", "es")
            gl = client_info.get("gl", "ES")
        elif getattr(flow.request, "content", None):
            hl, gl = extract_proto_context(flow.request.content)

        print(f"[INFO] YouTube: handling search for {query!r} (proto={wants_proto})")

        payload = {
            "context": {
                "client": {
                    "clientName": "ANDROID",
                    "clientVersion": "20.01.1",
                    "hl": hl,
                    "gl": gl,
                }
            },
            "query": query,
        }

        resp_data = await self._fetch_innertube("search", payload, as_proto=wants_proto)
        if not resp_data:
            fallback_payload = {
                "context": {
                    "client": {
                        "clientName": "ANDROID_TESTSUITE",
                        "clientVersion": "1.9",
                        "hl": hl,
                        "gl": gl,
                    }
                },
                "query": query,
            }
            resp_data = await self._fetch_innertube("search", fallback_payload, as_proto=wants_proto)

        if wants_proto and isinstance(resp_data, bytes):
            clean_proto = filter_proto(resp_data, drop_fields={777})
            flow.response = http.Response.make(
                200,
                clean_proto,
                {"Content-Type": "application/x-protobuf"},
            )
            print(f"[INFO] YouTube: successfully returned Protobuf search results for {query!r} ({len(clean_proto)} bytes)")
            return True

        if isinstance(resp_data, dict):
            # If search results already have sectionListRenderer, use directly; otherwise adapt
            if "contents" in resp_data and "sectionListRenderer" in resp_data["contents"]:
                cleaned_data = resp_data
            else:
                cleaned_data = self._adapt_search_response(resp_data)
            flow.response = http.Response.make(
                200,
                json.dumps(cleaned_data).encode("utf-8"),
                {"Content-Type": "application/json; charset=utf-8"},
            )
            print(f"[INFO] YouTube: successfully returned cleaned JSON search results for {query!r}")
            return True

        return False

    def _adapt_search_response(self, data: dict) -> dict:
        try:
            two_col = data.get("contents", {}).get("twoColumnSearchResultsRenderer", {})
            primary = two_col.get("primaryContents", {})
            sec_list = primary.get("sectionListRenderer", {})
            cleaned_sec_list = dict(sec_list)
            new_sections = []

            for sec in sec_list.get("contents", []):
                if "itemSectionRenderer" in sec:
                    isr = dict(sec["itemSectionRenderer"])
                    valid_items = []
                    for it in isr.get("contents", []):
                        k = list(it.keys())[0] if it else ""
                        if k in {"videoRenderer", "compactVideoRenderer", "channelRenderer", "shelfRenderer"}:
                            valid_items.append(it)
                    isr["contents"] = valid_items
                    new_sections.append({"itemSectionRenderer": isr})
                else:
                    new_sections.append(sec)

            cleaned_sec_list["contents"] = new_sections
            return {
                "responseContext": data.get("responseContext", {}),
                "contents": {
                    "sectionListRenderer": cleaned_sec_list
                },
            }
        except Exception as e:
            print(f"[WARN] YouTube search adaptation failed: {e}")
            return data

    async def handle_player(self, flow, body: dict, proto_fields: dict, wants_proto: bool) -> bool:
        video_id = ""
        if body:
            video_id = body.get("videoId", "")
        elif proto_fields:
            field2 = proto_fields.get(2, b"")
            if isinstance(field2, bytes):
                video_id = field2.decode("utf-8", "ignore")

        hl, gl = "es", "ES"
        if body:
            client_info = body.get("context", {}).get("client", {})
            hl = client_info.get("hl", "es")
            gl = client_info.get("gl", "ES")
        elif getattr(flow.request, "content", None):
            hl, gl = extract_proto_context(flow.request.content)

        print(f"[INFO] YouTube: handling player request for videoId={video_id!r} (proto={wants_proto})")

        android_payload = {
            "context": {
                "client": {
                    "clientName": "ANDROID",
                    "clientVersion": "20.01.1",
                    "hl": hl,
                    "gl": gl,
                }
            },
            "videoId": video_id,
        }

        if wants_proto:
            # Deliver Protobuf stream with progressive itag 18 MP4 from ANDROID client
            proto_data = await self._fetch_innertube("player", android_payload, as_proto=True)
            if isinstance(proto_data, bytes):
                # Cache real channelId if present in proto_data
                try:
                    cid = extract_channel_id_from_player_proto(proto_data)
                    if cid:
                        self._channel_cache[video_id] = cid
                except Exception:
                    pass

                clean_proto = filter_proto(proto_data, drop_fields={777})
                flow.response = http.Response.make(
                    200,
                    clean_proto,
                    {"Content-Type": "application/x-protobuf"},
                )
                print(f"[INFO] YouTube: successfully handled player for {video_id} -> Clean Protobuf ({len(clean_proto)} bytes, formats=progressive MP4)")
                return True
            return False

        # In JSON mode, use ANDROID progressive 360p stream
        android_data = await self._fetch_innertube("player", android_payload, as_proto=False)
        if isinstance(android_data, dict):
            cid = android_data.get("videoDetails", {}).get("channelId", "")
            if cid:
                self._channel_cache[video_id] = cid

            flow.response = http.Response.make(
                200,
                json.dumps(android_data).encode("utf-8"),
                {"Content-Type": "application/json; charset=utf-8"},
            )
            sd = android_data.get("streamingData", {})
            has_prog = bool(sd.get("formats"))
            print(f"[INFO] YouTube: successfully handled player for {video_id} (progressive={has_prog})")
            return True

        return False

    async def handle_next(self, flow, body: dict, proto_fields: dict, wants_proto: bool) -> bool:
        video_id = ""
        if body:
            video_id = body.get("videoId", "")
        elif proto_fields:
            field2 = proto_fields.get(2, b"")
            if isinstance(field2, bytes):
                video_id = field2.decode("utf-8", "ignore")

        hl, gl = "es", "ES"
        if body:
            client_info = body.get("context", {}).get("client", {})
            hl = client_info.get("hl", "es")
            gl = client_info.get("gl", "ES")
        elif getattr(flow.request, "content", None):
            hl, gl = extract_proto_context(flow.request.content)

        print(f"[INFO] YouTube: handling next for videoId={video_id!r} (proto={wants_proto})")

        payload = {
            "context": {
                "client": {
                    "clientName": "ANDROID_TESTSUITE",
                    "clientVersion": "1.9",
                    "hl": hl,
                    "gl": gl,
                }
            },
            "videoId": video_id,
        }

        resp_data = await self._fetch_innertube("next", payload, as_proto=wants_proto)

        # Retrieve channelId from cache or fetch from player
        channel_id = self._channel_cache.get(video_id, "")
        if not channel_id and video_id:
            try:
                p_resp = await self._fetch_innertube(
                    "player",
                    {"context": {"client": {"clientName": "ANDROID", "clientVersion": "20.01.1"}}, "videoId": video_id},
                    as_proto=False,
                )
                if isinstance(p_resp, dict):
                    channel_id = p_resp.get("videoDetails", {}).get("channelId", "")
                    if channel_id:
                        self._channel_cache[video_id] = channel_id
            except Exception:
                pass

        if wants_proto and isinstance(resp_data, bytes):
            clean_proto = filter_proto(resp_data, drop_fields={777})
            if channel_id:
                clean_proto = patch_next_proto(clean_proto, channel_id)
            flow.response = http.Response.make(
                200,
                clean_proto,
                {"Content-Type": "application/x-protobuf"},
            )
            print(f"[INFO] YouTube: successfully handled next for {video_id} -> Clean Protobuf ({len(clean_proto)} bytes, channelId={channel_id!r})")
            return True

        if isinstance(resp_data, dict):
            if channel_id:
                try:
                    results = resp_data.get("contents", {}).get("singleColumnWatchNextResults", {}).get("results", {}).get("results", {}).get("contents", [])
                    for sec in results:
                        for it in sec.get("itemSectionRenderer", {}).get("contents", []):
                            if "videoOwnerRenderer" in it:
                                vor = it["videoOwnerRenderer"]
                                vor["navigationEndpoint"] = {"browseEndpoint": {"browseId": channel_id}}
                                if "title" in vor and "runs" in vor["title"] and len(vor["title"]["runs"]) > 0:
                                    vor["title"]["runs"][0]["navigationEndpoint"] = {"browseEndpoint": {"browseId": channel_id}}
                except Exception:
                    pass

            flow.response = http.Response.make(
                200,
                json.dumps(resp_data).encode("utf-8"),
                {"Content-Type": "application/json; charset=utf-8"},
            )
            print(f"[INFO] YouTube: successfully handled next for {video_id} -> JSON (channelId={channel_id!r})")
            return True

        return False

    async def handle_guide(self, flow, body: dict, proto_fields: dict, wants_proto: bool) -> bool:
        hl, gl = "es", "ES"
        if body:
            client_info = body.get("context", {}).get("client", {})
            hl = client_info.get("hl", "es")
            gl = client_info.get("gl", "ES")
        elif getattr(flow.request, "content", None):
            hl, gl = extract_proto_context(flow.request.content)

        print(f"[INFO] YouTube: handling guide request (proto={wants_proto})")

        client_name = "IOS" if wants_proto else "WEB"
        client_version = "20.01.1" if wants_proto else "2.20240401.00.00"
        payload = {
            "context": {
                "client": {
                    "clientName": client_name,
                    "clientVersion": client_version,
                    "hl": hl,
                    "gl": gl,
                }
            }
        }

        resp_data = await self._fetch_innertube("guide", payload, as_proto=wants_proto)
        if wants_proto and isinstance(resp_data, bytes):
            clean_proto = filter_proto(resp_data, drop_fields={777})
            flow.response = http.Response.make(
                200,
                clean_proto,
                {"Content-Type": "application/x-protobuf"},
            )
            print(f"[INFO] YouTube: successfully handled guide -> Clean Protobuf ({len(clean_proto)} bytes)")
            return True

        if isinstance(resp_data, dict):
            flow.response = http.Response.make(
                200,
                json.dumps(resp_data).encode("utf-8"),
                {"Content-Type": "application/json; charset=utf-8"},
            )
            print(f"[INFO] YouTube: successfully handled guide -> JSON")
            return True

        # Fallback safe guide
        if wants_proto:
            flow.response = http.Response.make(
                200,
                b"\x0a\x00",
                {"Content-Type": "application/x-protobuf"},
            )
        else:
            flow.response = http.Response.make(
                200,
                b'{"responseContext":{}}',
                {"Content-Type": "application/json; charset=utf-8"},
            )
        return True

    async def handle_config(self, flow, body: dict, proto_fields: dict, wants_proto: bool) -> bool:
        hl, gl = "es", "ES"
        if body:
            client_info = body.get("context", {}).get("client", {})
            hl = client_info.get("hl", "es")
            gl = client_info.get("gl", "ES")
        elif getattr(flow.request, "content", None):
            hl, gl = extract_proto_context(flow.request.content)

        print(f"[INFO] YouTube: handling config request (proto={wants_proto})")

        payload = {
            "context": {
                "client": {
                    "clientName": "IOS",
                    "clientVersion": "11.19.7",
                    "hl": hl,
                    "gl": gl,
                }
            }
        }

        resp_data = await self._fetch_innertube("config", payload, as_proto=wants_proto)
        if wants_proto:
            if isinstance(resp_data, bytes) and len(resp_data) > 0:
                clean_proto = patch_proto_upgrade_config(resp_data)
            else:
                clean_proto = SAFE_ANTI_UPGRADE_PROTO

            flow.response = http.Response.make(
                200,
                clean_proto,
                {"Content-Type": "application/x-protobuf"},
            )
            print(f"[INFO] YouTube: successfully handled config -> Clean Anti-Upgrade Protobuf ({len(clean_proto)} bytes)")
            return True

        if isinstance(resp_data, dict):
            patched_data = patch_json_upgrade_config(resp_data)
        else:
            patched_data = SAFE_ANTI_UPGRADE_JSON

        flow.response = http.Response.make(
            200,
            json.dumps(patched_data).encode("utf-8"),
            {"Content-Type": "application/json; charset=utf-8"},
        )
        print(f"[INFO] YouTube: successfully handled config -> JSON Anti-Upgrade Config")
        return True

    async def request(self, flow) -> bool:
        if not is_youtube_request(flow):
            return False

        path = getattr(flow.request, "path", "").split("?")[0].lower()

        # 1. Detect if request is Protobuf or JSON first
        content_type = flow.request.headers.get("Content-Type", "").lower()
        accept = flow.request.headers.get("Accept", "").lower()
        raw_bytes = getattr(flow.request, "content", b"") or b""
        wants_proto = "protobuf" in content_type or "protobuf" in accept

        proto_fields = {}
        body = {}

        if wants_proto or (raw_bytes and not raw_bytes.startswith(b"{")):
            wants_proto = True
            try:
                proto_fields = extract_proto_fields(raw_bytes)
            except Exception as e:
                print(f"[WARN] YouTube: failed to parse incoming Protobuf fields: {e}")
        elif flow.request.method.upper() == "POST" and raw_bytes:
            try:
                body = json.loads(raw_bytes.decode("utf-8", errors="replace"))
            except Exception:
                body = {}

        # 2. Stub out obsolete push notification registration (prevent HTTP 400 & JSON in proto parser)
        if "notification_registration" in path:
            print(f"[INFO] YouTube: stubbing notification registration ({path}, proto={wants_proto})")
            if wants_proto:
                flow.response = http.Response.make(
                    200,
                    b"\x0a\x00",
                    {"Content-Type": "application/x-protobuf"},
                )
            else:
                flow.response = http.Response.make(
                    200,
                    b'{"responseContext":{}}',
                    {"Content-Type": "application/json; charset=utf-8"},
                )
            return True

        # 3. Stub out obsolete hot_config (HTTP 404 on Google servers)
        if "hot_config" in path:
            print(f"[INFO] YouTube: stubbing hot_config with anti-upgrade payload ({path}, proto={wants_proto})")
            if wants_proto:
                flow.response = http.Response.make(
                    200,
                    SAFE_ANTI_UPGRADE_PROTO,
                    {"Content-Type": "application/x-protobuf"},
                )
            else:
                flow.response = http.Response.make(
                    200,
                    json.dumps(SAFE_ANTI_UPGRADE_JSON).encode("utf-8"),
                    {"Content-Type": "application/json; charset=utf-8"},
                )
            return True

        # 4. Stub out settings, feedback, & interaction endpoints
        if "account/get_setting" in path or "account/set_setting" in path or "feedback" in path or "log_interaction" in path:
            print(f"[INFO] YouTube: stubbing {path} (proto={wants_proto})")
            if wants_proto:
                flow.response = http.Response.make(
                    200,
                    b"\x0a\x00",
                    {"Content-Type": "application/x-protobuf"},
                )
            else:
                flow.response = http.Response.make(
                    200,
                    b'{"responseContext":{}}',
                    {"Content-Type": "application/json; charset=utf-8"},
                )
            return True

        if "/youtubei/v1/browse" in path:
            return await self.handle_browse(flow, body, proto_fields, wants_proto)

        if "/youtubei/v1/player" in path:
            return await self.handle_player(flow, body, proto_fields, wants_proto)

        if "/youtubei/v1/search" in path:
            return await self.handle_search(flow, body, proto_fields, wants_proto)

        if "/youtubei/v1/next" in path:
            return await self.handle_next(flow, body, proto_fields, wants_proto)

        if "/youtubei/v1/guide" in path:
            return await self.handle_guide(flow, body, proto_fields, wants_proto)

        if "/youtubei/v1/config" in path:
            return await self.handle_config(flow, body, proto_fields, wants_proto)

        # 5. Catch-all safety for any remaining unhandled Innertube endpoint
        if "/youtubei/v1/" in path:
            print(f"[WARN] YouTube: catching unhandled Innertube endpoint {path} (proto={wants_proto})")
            if wants_proto:
                flow.response = http.Response.make(
                    200,
                    b"\x0a\x00",
                    {"Content-Type": "application/x-protobuf"},
                )
            else:
                flow.response = http.Response.make(
                    200,
                    b'{"responseContext":{}}',
                    {"Content-Type": "application/json; charset=utf-8"},
                )
            return True

        return False

    def response(self, flow) -> None:
        pass
