import asyncio
import json
import unittest
import urllib.parse
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.yahoo_weather import YahooWeatherProxy, WMO_TO_YAHOO_MAP


class YahooWeatherProxyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.proxy = YahooWeatherProxy()

    def test_matches_host(self):
        self.assertTrue(self.proxy.matches_host("msb-mobile.m.yahoo.com"))
        self.assertTrue(self.proxy.matches_host("unp.query.yahoo.com"))
        self.assertTrue(self.proxy.matches_host("query.yahooapis.com"))
        self.assertTrue(self.proxy.matches_host("weather.yahooapis.com"))
        self.assertTrue(self.proxy.matches_host("subdomain.query.yahoo.com"))
        self.assertTrue(self.proxy.matches_host("by.uservoice.com"))
        self.assertTrue(self.proxy.matches_host("api.crittercism.com"))
        self.assertFalse(self.proxy.matches_host("google.com"))
        self.assertFalse(self.proxy.matches_host("reddit.com"))

    async def test_telemetry_interception(self):
        flow = MagicMock()
        flow.request.pretty_host = "by.uservoice.com"
        flow.request.url = "https://by.uservoice.com/api/v1/tickets"
        flow.request.path = "/api/v1/tickets"
        flow.request.method = "POST"
        flow.request.raw_content = b"{}"

        handled = await self.proxy.request(flow)
        self.assertTrue(handled)
        self.assertEqual(flow.response.status_code, 200)
        self.assertEqual(flow.response.raw_content, b"{}")

    async def test_itunes_lookup_interception(self):
        flow = MagicMock()
        flow.request.pretty_host = "itunes.apple.com"
        flow.request.url = "http://itunes.apple.com/ES/lookup?bundleId=com.yahoo.weather"
        flow.request.path = "/ES/lookup"
        flow.request.method = "GET"
        flow.request.raw_content = b""

        handled = await self.proxy.request(flow)
        self.assertTrue(handled)
        self.assertEqual(flow.response.status_code, 200)
        data = json.loads(flow.response.raw_content.decode("utf-8"))
        self.assertEqual(data["resultCount"], 1)
        self.assertEqual(data["results"][0]["version"], "1.5.8")

    async def test_unp_interception(self):
        flow = MagicMock()
        flow.request.pretty_host = "unp.query.yahoo.com"
        flow.request.url = "https://unp.query.yahoo.com/v1/notification/register"
        flow.request.path = "/v1/notification/register"
        flow.request.method = "POST"
        flow.request.raw_content = b'{"deviceToken":"12345"}'

        handled = await self.proxy.request(flow)
        self.assertTrue(handled)
        self.assertEqual(flow.response.status_code, 200)
        data = json.loads(flow.response.raw_content.decode("utf-8"))
        self.assertEqual(data["status"], "ok")

    async def test_msb_interception(self):
        flow = MagicMock()
        flow.request.pretty_host = "msb-mobile.m.yahoo.com"
        flow.request.url = "https://msb-mobile.m.yahoo.com/ws/v1/startup"
        flow.request.path = "/ws/v1/startup"
        flow.request.method = "GET"
        flow.request.raw_content = b""

        handled = await self.proxy.request(flow)
        self.assertTrue(handled)
        self.assertEqual(flow.response.status_code, 200)
        data = json.loads(flow.response.raw_content.decode("utf-8"))
        self.assertEqual(data["status"], "ok")

    def test_format_yahoo_yql_response(self):
        mock_weather = {
            "current": {
                "temperature_2m": 22.4,
                "relative_humidity_2m": 45,
                "apparent_temperature": 21.8,
                "weather_code": 0,
                "surface_pressure": 1015.2,
                "wind_speed_10m": 12.5,
                "wind_direction_10m": 180,
            },
            "daily": {
                "time": ["2026-09-03", "2026-09-04"],
                "weather_code": [0, 1],
                "temperature_2m_max": [26.0, 27.5],
                "temperature_2m_min": [15.0, 16.2],
                "sunrise": ["2026-09-03T06:30"],
                "sunset": ["2026-09-03T20:15"],
            },
        }

        resp_str = self.proxy._format_yahoo_yql_response(
            mock_weather, 40.4168, -3.7038, "Madrid", "Spain", "Madrid"
        )
        data = json.loads(resp_str)

        self.assertIn("query", data)
        channel = data["query"]["results"]["channel"]
        self.assertEqual(channel["location"]["city"], "Madrid")
        self.assertEqual(channel["item"]["condition"]["temp"], "22")
        self.assertEqual(channel["item"]["condition"]["code"], "32")
        self.assertEqual(channel["item"]["condition"]["text"], "Sunny")
        self.assertEqual(len(channel["item"]["forecast"]), 2)
        self.assertEqual(channel["item"]["forecast"][0]["high"], "26")
        self.assertEqual(channel["item"]["forecast"][0]["low"], "15")

    async def test_weather_query_handling(self):
        mock_weather = {
            "current": {
                "temperature_2m": 18.0,
                "relative_humidity_2m": 60,
                "apparent_temperature": 18.0,
                "weather_code": 3,
                "surface_pressure": 1012.0,
                "wind_speed_10m": 8.0,
                "wind_direction_10m": 90,
            },
            "daily": {
                "time": ["2026-09-03"],
                "weather_code": [3],
                "temperature_2m_max": [20.0],
                "temperature_2m_min": [12.0],
                "sunrise": ["2026-09-03T07:00"],
                "sunset": ["2026-09-03T20:00"],
            },
        }

        with patch.object(self.proxy, "_fetch_open_meteo", AsyncMock(return_value=mock_weather)):
            flow = MagicMock()
            flow.request.pretty_host = "query.yahooapis.com"
            flow.request.url = "https://query.yahooapis.com/v1/public/yql?q=select%20*%20from%20weather.forecast%20where%20woeid%3D12345&format=json"
            flow.request.path = "/v1/public/yql"
            flow.request.method = "GET"
            flow.request.raw_content = b""

            handled = await self.proxy.request(flow)
            self.assertTrue(handled)
            self.assertEqual(flow.response.status_code, 200)
            data = json.loads(flow.response.raw_content.decode("utf-8"))
            channel = data["query"]["results"]["channel"]
            self.assertEqual(channel["item"]["condition"]["temp"], "18")
            self.assertEqual(channel["item"]["condition"]["code"], "26")
            self.assertEqual(channel["item"]["condition"]["text"], "Cloudy")

    async def test_geo_query_handling(self):
        flow = MagicMock()
        flow.request.pretty_host = "query.yahooapis.com"
        flow.request.url = "https://query.yahooapis.com/v1/public/yql?q=select%20woeid%20from%20geo.places%20where%20text%3D%22Madrid%22&format=json"
        flow.request.path = "/v1/public/yql"
        flow.request.method = "GET"
        flow.request.raw_content = b""

        handled = await self.proxy.request(flow)
        self.assertTrue(handled)
        self.assertEqual(flow.response.status_code, 200)
        data = json.loads(flow.response.raw_content.decode("utf-8"))
        self.assertEqual(data["query"]["results"]["place"]["woeid"], "766273")

    async def test_multi_query_handling(self):
        mock_weather = {
            "current": {
                "temperature_2m": 22.0,
                "apparent_temperature": 21.0,
                "relative_humidity_2m": 60,
                "weather_code": 0,
                "surface_pressure": 1015.0,
                "wind_speed_10m": 12.0,
                "wind_direction_10m": 180.0,
            },
            "daily": {
                "time": ["2026-09-03"],
                "weather_code": [0],
                "temperature_2m_max": [25.0],
                "temperature_2m_min": [15.0],
                "sunrise": ["2026-09-03T07:00"],
                "sunset": ["2026-09-03T20:00"],
                "uv_index_max": [6.0],
            },
            "hourly": {
                "time": ["2026-09-03T19:00"],
                "temperature_2m": [22.0],
                "weather_code": [0],
                "precipitation_probability": [0],
            },
        }

        with patch.object(self.proxy, "_fetch_open_meteo", AsyncMock(return_value=mock_weather)):
            flow = MagicMock()
            flow.request.pretty_host = "mobileweather.yql.yahooapis.com"
            query_str = (
                "select * from yql.query.multi where queries=\""
                "select * from yahoo.media.weather.oauth where flickrGroup='1463451@N25' AND hourly='TRUE' AND hours='23' AND days='10' AND pw='1316' AND ph='1316' AND uv='TRUE' AND unit='C' AND mp='true' AND lang='es' AND lat=42.799072 AND lon=-8.258439; "
                "select * from yahoo.media.weather.oauth where flickrGroup='1463451@N25' AND hourly='TRUE' AND hours='23' AND days='10' AND pw='1316' AND ph='1316' AND uv='TRUE' AND unit='C' AND mp='true' AND lang='es' AND woeid in (753692,766273)\""
            )
            encoded_q = urllib.parse.quote(query_str)
            flow.request.url = f"https://mobileweather.yql.yahooapis.com/v1/yql?format=json&q={encoded_q}"
            flow.request.path = "/v1/yql"
            flow.request.method = "GET"
            flow.request.raw_content = b""

            handled = await self.proxy.request(flow)
            self.assertTrue(handled)
            self.assertEqual(flow.response.status_code, 200)
            data = json.loads(flow.response.raw_content.decode("utf-8"))
            channels_list = data["query"]["results"]["channel"]
            self.assertEqual(len(channels_list), 3)
            # Channel for coords (Galicia / Lalín)
            self.assertEqual(channels_list[0]["location"]["city"], "Lalín")
            self.assertEqual(channels_list[0]["item"]["condition"]["text"], "Despejado")
            self.assertTrue(len(channels_list[0]["item"]["forecast"]) >= 1)
            # Channels for WOEID 753692 (Barcelona) and 766273 (Madrid)
            self.assertEqual(channels_list[1]["location"]["city"], "Barcelona")
            self.assertEqual(channels_list[2]["location"]["city"], "Madrid")
            # Verify results.results structure
            results_arr = data["query"]["results"]["results"]
            self.assertEqual(len(results_arr), 2)
            self.assertEqual(results_arr[0]["channel"]["location"]["city"], "Lalín")
            self.assertEqual(len(results_arr[1]["channel"]), 2)


if __name__ == "__main__":
    unittest.main()
