import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
import json
from src.services.youtube import (
    YouTubeProxy,
    is_youtube_request,
    extract_proto_fields,
    extract_proto_context,
    SAFE_ANTI_UPGRADE_PROTO,
    SAFE_ANTI_UPGRADE_JSON,
    patch_next_proto,
)

class TestYouTubeProxy(unittest.TestCase):
    def setUp(self):
        self.proxy = YouTubeProxy()

    def test_is_youtube_request(self):
        flow1 = SimpleNamespace(
            request=SimpleNamespace(
                pretty_host="www.googleapis.com",
                path="/youtubei/v1/config",
                headers={"User-Agent": "com.google.ios.youtube/11.19.7 (iPhone4,1; U; CPU OS 7_1_2 like Mac OS X; es_ES)"},
            )
        )
        self.assertTrue(is_youtube_request(flow1))

        flow2 = SimpleNamespace(
            request=SimpleNamespace(
                pretty_host="www.googleapis.com",
                path="/youtubei/v1/browse?key=AIzaSyB...",
                headers={"User-Agent": "CustomClient"},
            )
        )
        self.assertTrue(is_youtube_request(flow2))

        flow3 = SimpleNamespace(
            request=SimpleNamespace(
                pretty_host="youtubei.googleapis.com",
                path="/anything",
                headers={"User-Agent": "Mozilla/5.0"},
            )
        )
        self.assertTrue(is_youtube_request(flow3))

        flow4 = SimpleNamespace(
            request=SimpleNamespace(
                pretty_host="api.imdbws.com",
                path="/categories",
                headers={"User-Agent": "IMDb_Android/8.6.0"},
            )
        )
        self.assertFalse(is_youtube_request(flow4))

    def test_extract_proto_fields(self):
        # field 2: "FEwhat_to_watch" (wire type 2, length 15)
        raw = b"\x12\x0fFEwhat_to_watch\x1a\x06params"
        f = extract_proto_fields(raw)
        self.assertEqual(f[2], b"FEwhat_to_watch")
        self.assertEqual(f[3], b"params")

    def test_notification_registration_stubbing(self):
        flow = SimpleNamespace(
            request=SimpleNamespace(
                method="POST",
                pretty_host="www.googleapis.com",
                path="/youtubei/v1/notification_registration/register",
                headers={"User-Agent": "com.google.ios.youtube/11.19.7", "Content-Type": "application/json"},
                content=b"{}",
                text="{}",
            ),
            response=None,
        )
        import asyncio
        handled = asyncio.run(self.proxy.request(flow))
        self.assertTrue(handled)
        self.assertEqual(flow.response.status_code, 200)
        data = json.loads(flow.response.text)
        self.assertIn("responseContext", data)

    def test_notification_registration_stubbing_proto_mode(self):
        flow = SimpleNamespace(
            request=SimpleNamespace(
                method="POST",
                pretty_host="www.googleapis.com",
                path="/youtubei/v1/notification_registration/set_registration",
                headers={"User-Agent": "com.google.ios.youtube/11.19.7", "Content-Type": "application/x-protobuf"},
                content=b"\x0a\x05token",
                text="",
            ),
            response=None,
        )
        import asyncio
        handled = asyncio.run(self.proxy.request(flow))
        self.assertTrue(handled)
        self.assertEqual(flow.response.status_code, 200)
        self.assertEqual(flow.response.headers.get("Content-Type"), "application/x-protobuf")
        self.assertEqual(flow.response.content, b"\x0a\x00")

    def test_hot_config_stubbing(self):
        flow = SimpleNamespace(
            request=SimpleNamespace(
                method="POST",
                pretty_host="www.googleapis.com",
                path="/youtubei/v1/hot_config",
                headers={"User-Agent": "com.google.ios.youtube/11.19.7", "Content-Type": "application/x-protobuf"},
                content=b"\x0a\x00",
                text="",
            ),
            response=None,
        )
        import asyncio
        handled = asyncio.run(self.proxy.request(flow))
        self.assertTrue(handled)
        self.assertEqual(flow.response.status_code, 200)
        self.assertEqual(flow.response.headers.get("Content-Type"), "application/x-protobuf")
        f = extract_proto_fields(flow.response.content)
        self.assertIn(3, f)
        f3 = extract_proto_fields(f[3])
        self.assertIn(63102527, f3)
        upg = extract_proto_fields(f3[63102527])
        self.assertEqual(upg.get(2), 0)  # force = 0
        self.assertEqual(upg.get(5), b"1.0.0")  # forceBelowVersion = "1.0.0"

    def test_config_anti_upgrade_proto(self):
        # Simulate Google returning force: true, forceBelowVersion: 20.10
        # Field 3 -> Subfield 63102527 -> {2: 1, 5: "20.10"}
        google_proto = bytes.fromhex("0a001a14fae3dbf0010c10012a0532302e3130")
        flow = SimpleNamespace(
            request=SimpleNamespace(
                method="POST",
                pretty_host="www.googleapis.com",
                path="/youtubei/v1/config",
                headers={"User-Agent": "com.google.ios.youtube/11.19.7", "Content-Type": "application/x-protobuf"},
                content=b"\x0a\x00",
                text="",
            ),
            response=None,
        )
        import asyncio
        with patch.object(self.proxy, "_fetch_innertube", new=AsyncMock(return_value=google_proto)):
            handled = asyncio.run(self.proxy.handle_config(flow, {}, {}, True))
            self.assertTrue(handled)
            self.assertEqual(flow.response.status_code, 200)
            self.assertEqual(flow.response.headers.get("Content-Type"), "application/x-protobuf")
            f = extract_proto_fields(flow.response.content)
            self.assertIn(3, f)
            f3 = extract_proto_fields(f[3])
            upg = extract_proto_fields(f3[63102527])
            self.assertEqual(upg.get(1), 0)  # prompt = 0
            self.assertEqual(upg.get(2), 0)  # force = 0
            self.assertEqual(upg.get(4), b"1.0.0")
            self.assertEqual(upg.get(5), b"1.0.0")

    def test_config_anti_upgrade_json(self):
        google_json = {
            "responseContext": {},
            "globalConfig": {
                "upgradeConfig": {"force": True, "forceBelowVersion": "20.10"}
            }
        }
        flow = SimpleNamespace(
            request=SimpleNamespace(
                method="POST",
                pretty_host="www.googleapis.com",
                path="/youtubei/v1/config",
                headers={"User-Agent": "com.google.ios.youtube/11.19.7", "Content-Type": "application/json"},
                content=b"{}",
                text="{}",
            ),
            response=None,
        )
        import asyncio
        with patch.object(self.proxy, "_fetch_innertube", new=AsyncMock(return_value=google_json)):
            handled = asyncio.run(self.proxy.handle_config(flow, {}, {}, False))
            self.assertTrue(handled)
            self.assertEqual(flow.response.status_code, 200)
            res = json.loads(flow.response.text)
            self.assertFalse(res["globalConfig"]["upgradeConfig"]["force"])
            self.assertEqual(res["globalConfig"]["upgradeConfig"]["forceBelowVersion"], "1.0.0")
            self.assertFalse(res["globalConfig"]["upgradeConfig"]["prompt"])

    def test_search_adaptation(self):
        sample_web_search = {
            "responseContext": {"visitorData": "xyz"},
            "contents": {
                "twoColumnSearchResultsRenderer": {
                    "primaryContents": {
                        "sectionListRenderer": {
                            "contents": [
                                {
                                    "itemSectionRenderer": {
                                        "contents": [
                                            {"channelRenderer": {"channelId": "UC123"}},
                                            {"gridShelfViewModel": {"unsupported": True}},
                                            {"videoRenderer": {"videoId": "abc456", "title": {"runs": [{"text": "Video 1"}]}}},
                                        ]
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        }
        cleaned = self.proxy._adapt_search_response(sample_web_search)
        self.assertIn("sectionListRenderer", cleaned["contents"])
        items = cleaned["contents"]["sectionListRenderer"]["contents"][0]["itemSectionRenderer"]["contents"]
        self.assertEqual(len(items), 2)
        self.assertEqual(list(items[0].keys())[0], "channelRenderer")
        self.assertEqual(list(items[1].keys())[0], "videoRenderer")

    def test_handle_browse_fe_trending_mapping_json(self):
        import asyncio
        flow = SimpleNamespace(
            request=SimpleNamespace(
                method="POST",
                pretty_host="www.googleapis.com",
                path="/youtubei/v1/browse",
                headers={"User-Agent": "com.google.ios.youtube/11.19.7"},
                query={},
                content=b'{"browseId": "FEtrending"}',
                text='{"browseId": "FEtrending"}',
            ),
            response=None,
        )
        fake_response = {
            "contents": {"singleColumnBrowseResultsRenderer": {"tabs": []}}
        }
        with patch.object(self.proxy, "_fetch_innertube", new=AsyncMock(return_value=fake_response)) as mock_fetch:
            handled = asyncio.run(self.proxy.handle_browse(flow, {"browseId": "FEtrending"}, {}, False))
            self.assertTrue(handled)
            self.assertEqual(flow.response.status_code, 200)
            mock_fetch.assert_called_once()
            called_payload = mock_fetch.call_args[0][1]
            self.assertEqual(called_payload["browseId"], "FEwhat_to_watch")
            self.assertEqual(called_payload["context"]["client"]["clientName"], "ANDROID_TESTSUITE")

    def test_handle_browse_protobuf_mode(self):
        import asyncio
        fake_proto_response = b"\n\x08testdata"
        flow = SimpleNamespace(
            request=SimpleNamespace(
                method="POST",
                pretty_host="www.googleapis.com",
                path="/youtubei/v1/browse",
                headers={"User-Agent": "com.google.ios.youtube/11.19.7", "Content-Type": "application/x-protobuf"},
                query={},
                content=b"\x12\x0fFEwhat_to_watch",
                text="",
            ),
            response=None,
        )
        with patch.object(self.proxy, "_fetch_innertube", new=AsyncMock(return_value=fake_proto_response)) as mock_fetch:
            handled = asyncio.run(self.proxy.request(flow))
            self.assertTrue(handled)
            self.assertEqual(flow.response.status_code, 200)
            self.assertEqual(flow.response.headers.get("Content-Type"), "application/x-protobuf")
            self.assertEqual(flow.response.content, fake_proto_response)
            # Verify alt=proto was requested
            self.assertTrue(mock_fetch.call_args[1].get("as_proto", False))

    def test_handle_player_progressive_json(self):
        import asyncio
        flow = SimpleNamespace(
            request=SimpleNamespace(
                method="POST",
                pretty_host="www.googleapis.com",
                path="/youtubei/v1/player",
                headers={"User-Agent": "com.google.ios.youtube/11.19.7", "Content-Type": "application/json"},
                query={},
                content=b'{"videoId": "test123"}',
                text='{"videoId": "test123"}',
            ),
            response=None,
        )
        fake_android = {
            "streamingData": {
                "formats": [{"itag": 18, "url": "https://rr.googlevideo.com/videoplayback?itag=18"}],
            },
            "videoDetails": {"title": "Test Video", "channelId": "UC1234567890123456789012"},
        }
        with patch.object(self.proxy, "_fetch_innertube", new=AsyncMock(return_value=fake_android)):
            handled = asyncio.run(self.proxy.handle_player(flow, {"videoId": "test123"}, {}, False))
            self.assertTrue(handled)
            self.assertEqual(flow.response.status_code, 200)
            data = json.loads(flow.response.text)
            self.assertEqual(len(data["streamingData"]["formats"]), 1)
            self.assertEqual(data["streamingData"]["formats"][0]["itag"], 18)
            self.assertEqual(self.proxy._channel_cache.get("test123"), "UC1234567890123456789012")

    def test_handle_browse_channel_mweb(self):
        import asyncio
        flow = SimpleNamespace(
            request=SimpleNamespace(
                method="POST",
                pretty_host="www.googleapis.com",
                path="/youtubei/v1/browse",
                headers={"User-Agent": "com.google.ios.youtube/11.19.7", "Content-Type": "application/x-protobuf"},
                query={},
                content=b"\x12\x18UC1234567890123456789012",
                text="",
            ),
            response=None,
        )
        fake_proto = b"\x0a\x00"
        with patch.object(self.proxy, "_fetch_innertube", new=AsyncMock(return_value=fake_proto)) as mock_fetch:
            handled = asyncio.run(self.proxy.request(flow))
            self.assertTrue(handled)
            self.assertEqual(flow.response.status_code, 200)
            called_payload = mock_fetch.call_args[0][1]
            self.assertEqual(called_payload["context"]["client"]["clientName"], "MWEB")

    def test_patch_next_proto(self):
        # Simulate an ANDROID_TESTSUITE next response with videoOwnerRenderer
        from src.services.youtube import encode_field, encode_varint
        vor_body = encode_field(1, 2, b"thumbnail_data") + encode_field(2, 2, b"title_data")
        tag_vor = encode_varint((51779708 << 3) | 2)
        vor_field = tag_vor + encode_varint(len(vor_body)) + vor_body
        
        tag_isr = encode_varint((50195462 << 3) | 2)
        isr_field = tag_isr + encode_varint(len(vor_field)) + vor_field
        
        dummy_proto = isr_field
        patched = patch_next_proto(dummy_proto, "UC1234567890123456789012")
        self.assertGreater(len(patched), len(dummy_proto))
        self.assertIn(b"UC1234567890123456789012", patched)

    def test_extract_channel_id_from_player_proto(self):
        from src.services.youtube import extract_channel_id_from_player_proto, encode_field
        # Field 11 (videoDetails) -> Subfield 19 (channelId)
        cid = b"UC1234567890123456789012"
        vd = encode_field(19, 2, cid)
        player_proto = encode_field(11, 2, vd)
        extracted = extract_channel_id_from_player_proto(player_proto)
        self.assertEqual(extracted, "UC1234567890123456789012")

if __name__ == "__main__":
    unittest.main()
