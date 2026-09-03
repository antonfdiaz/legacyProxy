import asyncio
import datetime
import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
from mitmproxy import http

YAHOO_WEATHER_HOSTS = {
    "msb-mobile.m.yahoo.com",
    "unp.query.yahoo.com",
    "query.yahooapis.com",
    "weather.yahooapis.com",
    "weather-ydn-yql.media.yahoo.com",
    "mobileweather.yql.yahooapis.com",
    "config.mobile.yahoo.com",
    "geo.yahoo.com",
    "m.yahoo.com",
    "weather.yahoo.com",
    "where.yahooapis.com",
    "geo.yahooapis.com",
    "api.flickr.com",
}

YAHOO_TELEMETRY_HOSTS = {
    "by.uservoice.com",
    "api.crittercism.com",
    "data.flurry.com",
    "ads.flurry.com",
    "prompt.flurry.com",
}

WOEID_MAP = {
    753692: {"city": "Barcelona", "country": "España", "region": "Cataluña", "lat": 41.3888, "lon": 2.1590},
    766273: {"city": "Madrid", "country": "España", "region": "Madrid", "lat": 40.4168, "lon": -3.7038},
    777925: {"city": "Valencia", "country": "España", "region": "Valencia", "lat": 39.4699, "lon": -0.3763},
    774508: {"city": "Sevilla", "country": "España", "region": "Andalucía", "lat": 37.3891, "lon": -5.9845},
    779063: {"city": "Zaragoza", "country": "España", "region": "Aragón", "lat": 41.6488, "lon": -0.8891},
    765876: {"city": "Málaga", "country": "España", "region": "Andalucía", "lat": 36.7213, "lon": -4.4214},
    754542: {"city": "Bilbao", "country": "España", "region": "País Vasco", "lat": 43.2630, "lon": -2.9350},
    773968: {"city": "Santiago de Compostela", "country": "España", "region": "Galicia", "lat": 42.8782, "lon": -8.5448},
    765451: {"city": "Lalín", "country": "España", "region": "Galicia", "lat": 42.6617, "lon": -8.1133},
    764267: {"city": "A Coruña", "country": "España", "region": "Galicia", "lat": 43.3623, "lon": -8.4115},
    778004: {"city": "Vigo", "country": "España", "region": "Galicia", "lat": 42.2406, "lon": -8.7207},
    769293: {"city": "Ourense", "country": "España", "region": "Galicia", "lat": 42.3358, "lon": -7.8639},
    766155: {"city": "Lugo", "country": "España", "region": "Galicia", "lat": 43.0097, "lon": -7.5560},
    766299: {"city": "Pontevedra", "country": "España", "region": "Galicia", "lat": 42.4336, "lon": -8.6480},
    44418: {"city": "London", "country": "United Kingdom", "region": "Greater London", "lat": 51.5074, "lon": -0.1278},
    2459115: {"city": "New York", "country": "United States", "region": "New York", "lat": 40.7128, "lon": -74.0060},
}

WMO_TO_YAHOO_MAP = {
    0: (32, "Sunny", "Despejado"),
    1: (34, "Mostly Sunny", "Mayormente soleado"),
    2: (30, "Partly Cloudy", "Parcialmente nublado"),
    3: (26, "Cloudy", "Nublado"),
    45: (20, "Foggy", "Niebla"),
    48: (20, "Depositing Rime Fog", "Niebla"),
    51: (9, "Light Drizzle", "Llovizna ligera"),
    53: (9, "Drizzle", "Llovizna"),
    55: (9, "Heavy Drizzle", "Llovizna densa"),
    56: (8, "Freezing Drizzle", "Llovizna helada"),
    57: (8, "Dense Freezing Drizzle", "Llovizna helada"),
    61: (11, "Slight Rain", "Lluvia ligera"),
    63: (11, "Moderate Rain", "Lluvia moderada"),
    65: (12, "Heavy Rain", "Lluvia fuerte"),
    66: (10, "Freezing Rain", "Lluvia helada"),
    67: (10, "Heavy Freezing Rain", "Lluvia helada fuerte"),
    71: (14, "Slight Snow Fall", "Nieve ligera"),
    73: (14, "Moderate Snow Fall", "Nieve moderada"),
    75: (16, "Heavy Snow Fall", "Nieve fuerte"),
    77: (18, "Snow Grains", "Granizo fino"),
    80: (11, "Slight Rain Showers", "Chubascos ligeros"),
    81: (12, "Moderate Rain Showers", "Chubascos"),
    82: (12, "Violent Rain Showers", "Chubascos violentos"),
    85: (14, "Slight Snow Showers", "Chubascos de nieve"),
    86: (16, "Heavy Snow Showers", "Chubascos de nieve fuertes"),
    95: (4, "Thunderstorm", "Tormenta"),
    96: (4, "Thunderstorm with Slight Hail", "Tormenta con granizo"),
    99: (4, "Thunderstorm with Heavy Hail", "Tormenta con granizo fuerte"),
}

SPANISH_DAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
ENGLISH_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class YahooWeatherProxy:
    def __init__(self, config=None):
        self.config = config
        self._cache = {}

    def matches_host(self, host: str) -> bool:
        host = host.lower().rstrip(".")
        if host in YAHOO_WEATHER_HOSTS or host in YAHOO_TELEMETRY_HOSTS:
            return True
        if host.endswith(".query.yahoo.com") or host.endswith(".weather.yahooapis.com"):
            return True
        if host.endswith(".uservoice.com") or host.endswith(".crittercism.com") or host.endswith(".flurry.com"):
            return True
        if "flickr.com" in host:
            return True
        if "yimg.com" in host:
            return True
        return False

    async def request(self, flow: http.HTTPFlow) -> bool:
        host = (flow.request.pretty_host or "").lower().rstrip(".")
        url = flow.request.url
        path = flow.request.path.split("?", 1)[0]

        # 1. Intercept App Store lookup for com.yahoo.weather
        if "itunes.apple.com" in host and ("com.yahoo.weather" in url or "628677149" in url):
            print(f"[INFO] Intercepted iTunes lookup for Yahoo Weather: {url}")
            mock_itunes = {
                "resultCount": 1,
                "results": [
                    {
                        "version": "1.5.8",
                        "bundleId": "com.yahoo.weather",
                        "trackId": 628677149,
                        "trackName": "Yahoo Weather",
                        "minimumOsVersion": "7.0",
                        "sellerName": "Yahoo",
                    }
                ],
            }
            flow.response = http.Response.make(
                200,
                json.dumps(mock_itunes).encode("utf-8"),
                {
                    "Content-Type": "application/json; charset=utf-8",
                    "Cache-Control": "max-age=3600",
                },
            )
            return True

        if not self.matches_host(host):
            return False

        print(f"[INFO] Yahoo Weather proxy handling {flow.request.method} {url}")

        # 2. Silence Telemetry and Crash Reports
        if "crittercism.com" in host:
            raw = flow.request.raw_content or b""
            try:
                import zlib
                decompressed = zlib.decompress(raw, 16 + zlib.MAX_WBITS)
                print(f"[CRITTERCISM CRASH LOG]: {decompressed.decode('utf-8', errors='replace')[:4000]}")
            except Exception:
                try:
                    import zlib
                    decompressed = zlib.decompress(raw)
                    print(f"[CRITTERCISM CRASH LOG]: {decompressed.decode('utf-8', errors='replace')[:4000]}")
                except Exception:
                    print(f"[CRITTERCISM CRASH LOG RAW]: {raw.decode('utf-8', errors='replace')[:4000]}")
            flow.response = http.Response.make(
                200,
                b"{}",
                {"Content-Type": "application/json; charset=utf-8"},
            )
            return True

        if host in YAHOO_TELEMETRY_HOSTS or host.endswith(".uservoice.com") or host.endswith(".flurry.com"):
            flow.response = http.Response.make(
                200,
                b"{}",
                {"Content-Type": "application/json; charset=utf-8"},
            )
            return True

        # 3. Intercept Yahoo Universal Notification Platform
        if host == "unp.query.yahoo.com" or "unp." in host:
            print(f"[INFO] Intercepted Yahoo UNP notification request: {url}")
            flow.response = http.Response.make(
                200,
                b'{"status":"ok","code":200}',
                {
                    "Content-Type": "application/json; charset=utf-8",
                    "Cache-Control": "no-store",
                },
            )
            return True

        # 4. Intercept config endpoints
        if "config.json" in path or "getConfig.php" in path or "config.mobile.yahoo.com" in host:
            print(f"[INFO] Intercepted Yahoo Mobile Config request: {url}")
            flow.response = http.Response.make(
                200,
                b'{}',
                {
                    "Content-Type": "application/json; charset=utf-8",
                    "Cache-Control": "no-store",
                },
            )
            return True

        # 4b. Let other static assets on yimg.com (images, icons) stream through to live CDN
        if "yimg.com" in host:
            return False

        # 5. Intercept MSB (Mobile Service Bus) endpoints
        if host == "msb-mobile.m.yahoo.com" or "msb-" in host:
            body_preview = (flow.request.raw_content or b"")[:500].decode("utf-8", errors="replace")
            print(f"[INFO] Intercepted MSB request ({flow.request.method} {path}): body={body_preview}")
            if "weather" in url.lower() or "weather" in body_preview.lower():
                weather_json = await self._handle_weather_query(flow)
                flow.response = http.Response.make(
                    200,
                    weather_json.encode("utf-8"),
                    {"Content-Type": "application/json; charset=utf-8"},
                )
                return True

            flow.response = http.Response.make(
                200,
                b'{"status":"ok","result":"success"}',
                {
                    "Content-Type": "application/json; charset=utf-8",
                    "Cache-Control": "no-store",
                },
            )
            return True

        # 6. Intercept YQL / Yahoo Weather queries
        if (
            host in {"query.yahooapis.com", "weather.yahooapis.com", "weather-ydn-yql.media.yahoo.com", "mobileweather.yql.yahooapis.com"}
            or "query.yahoo.com" in host
            or "yahooapis.com" in host
            or "weather" in path
            or "yql" in path
        ):
            print(f"[INFO] Handling Yahoo Weather YQL / API query: {url}")
            try:
                weather_json = await self._handle_weather_query(flow)
                flow.response = http.Response.make(
                    200,
                    weather_json.encode("utf-8"),
                    {
                        "Content-Type": "application/json; charset=utf-8",
                        "Access-Control-Allow-Origin": "*",
                        "Cache-Control": "public, max-age=300",
                    },
                )
                return True
            except Exception as e:
                print(f"[WARN] Failed to handle Yahoo weather query: {e}")
                import traceback
                traceback.print_exc()

        # 7. Intercept Flickr photo group queries
        if "flickr.com" in host:
            print(f"[INFO] Intercepted Flickr Weather photo request: {url}")
            flow.response = http.Response.make(
                200,
                b'{"stat":"ok","photos":{"page":1,"pages":1,"perpage":1,"total":"0","photo":[]}}',
                {"Content-Type": "application/json; charset=utf-8"},
            )
            return True

        # Fallback
        flow.response = http.Response.make(
            200,
            b'{"status":"ok"}',
            {"Content-Type": "application/json; charset=utf-8"},
        )
        return True

    def error(self, flow: http.HTTPFlow) -> bool:
        host = (flow.request.pretty_host or "").lower().rstrip(".")
        if self.matches_host(host):
            print(f"[INFO] Intercepting connection failure for Yahoo host {host}")
            flow.response = http.Response.make(
                200,
                b'{"status":"ok","error":null}',
                {"Content-Type": "application/json; charset=utf-8"},
            )
            return True
        return False

    async def _handle_weather_query(self, flow: http.HTTPFlow) -> str:
        url = flow.request.url
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)

        q = params.get("q", [""])[0]
        if not q and flow.request.raw_content:
            try:
                body_json = json.loads(flow.request.raw_content.decode("utf-8"))
                q = body_json.get("q", "")
            except Exception:
                pass

        # Check for geo query
        if "geo.places" in q or "geo.placefinder" in q or "places" in parsed.path or "placefinder" in parsed.path:
            text_match = re.search(r'text\s*=\s*["\']([^"\']+)["\']', q, re.I)
            city_name = text_match.group(1).split(",")[0].strip() if text_match else "Madrid"
            coords = await self._geocode_location(city_name)
            lat, lon, country = (coords[0], coords[1], coords[3]) if coords else (40.4168, -3.7038, "España")
            return self._format_yahoo_geo_response(city_name, country, lat, lon)

        # Check for yql.query.multi
        if "yql.query.multi" in q.lower():
            return await self._handle_multi_query(q)

        # Single query
        return await self._handle_single_query(q)

    async def _handle_multi_query(self, q: str) -> str:
        queries_match = re.search(r'queries=["\'](.*?)["\']\s*(?:$|\))', q, re.DOTALL | re.I)
        raw_queries = queries_match.group(1) if queries_match else q
        subqueries = [sq.strip() for sq in raw_queries.split(";") if sq.strip()]

        subquery_results = []
        all_channels = []
        for sq in subqueries:
            chs = await self._process_subquery_channels(sq)
            all_channels.extend(chs)
            if len(chs) == 1:
                subquery_results.append({"channel": chs[0]})
            else:
                subquery_results.append({"channel": chs})

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        now_date_str = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        lang_m = re.search(r"lang\s*=\s*['\"]([^'\"]+)['\"]", q, re.I)
        lang = lang_m.group(1).lower() if lang_m else "en"

        response_dict = {
            "query": {
                "count": len(subquery_results),
                "created": now_date_str,
                "lang": lang,
                "results": {
                    "results": subquery_results,
                    "channel": all_channels if len(all_channels) > 1 else (all_channels[0] if all_channels else {}),
                },
            }
        }
        return json.dumps(response_dict)

    async def _handle_single_query(self, q: str) -> str:
        channels = await self._process_subquery_channels(q)
        ch = channels[0] if channels else {}

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        now_date_str = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        lang_m = re.search(r"lang\s*=\s*['\"]([^'\"]+)['\"]", q, re.I)
        lang = lang_m.group(1).lower() if lang_m else "en"

        response_dict = {
            "query": {
                "count": 1,
                "created": now_date_str,
                "lang": lang,
                "results": {
                    "channel": ch,
                },
            }
        }
        return json.dumps(response_dict)

    async def _process_subquery_channels(self, sq: str) -> List[dict]:
        woeid_in_m = re.search(r"woeid\s+in\s*\(([^)]+)\)", sq, re.I)
        woeid_eq_m = re.search(r"woeid\s*=\s*(\d+)", sq, re.I)
        lat_m = re.search(r"lat\s*=\s*(-?\d+(?:\.\d+)?)", sq, re.I)
        lon_m = re.search(r"lon\s*=\s*(-?\d+(?:\.\d+)?)", sq, re.I)
        lang_m = re.search(r"lang\s*=\s*['\"]([^'\"]+)['\"]", sq, re.I)
        lang = lang_m.group(1).lower() if lang_m else "en"

        if woeid_in_m:
            ids = [x.strip().strip("'\"") for x in woeid_in_m.group(1).split(",") if x.strip()]
            channels = []
            for wid_str in ids:
                try:
                    wid = int(wid_str)
                except ValueError:
                    wid = 766273
                ch = await self._get_channel_for_woeid(wid, lang=lang)
                channels.append(ch)
            return channels

        elif woeid_eq_m:
            wid = int(woeid_eq_m.group(1))
            ch = await self._get_channel_for_woeid(wid, lang=lang)
            return [ch]

        elif lat_m and lon_m:
            lat = float(lat_m.group(1))
            lon = float(lon_m.group(1))
            ch = await self._get_channel_for_coords(lat, lon, lang=lang)
            return [ch]

        else:
            ch = await self._get_channel_for_woeid(766273, lang=lang)
            return [ch]

    async def _get_channel_for_woeid(self, woeid: int, lang: str = "es") -> dict:
        info = WOEID_MAP.get(woeid)
        if info:
            lat = info["lat"]
            lon = info["lon"]
            city = info["city"]
            country = info["country"]
            region = info["region"]
        else:
            lat = 40.4168
            lon = -3.7038
            city = f"Ciudad {woeid}"
            country = "España"
            region = ""

        weather_data = await self._fetch_open_meteo(lat, lon)
        return self._build_channel_dict(weather_data, lat, lon, city, country, region, woeid, lang=lang)

    async def _get_channel_for_coords(self, lat: float, lon: float, lang: str = "es") -> dict:
        # User location (approx. Galicia)
        if abs(lat - 42.8) < 0.6 and abs(lon - (-8.26)) < 0.6:
            city = "Lalín"
            country = "España"
            region = "Galicia"
            woeid = 765451
        else:
            coords = await self._geocode_coords(lat, lon)
            if coords:
                city, country, region = coords
            else:
                city = f"{lat:.2f}, {lon:.2f}"
                country = "España"
                region = ""
            woeid = 765451

        weather_data = await self._fetch_open_meteo(lat, lon)
        return self._build_channel_dict(weather_data, lat, lon, city, country, region, woeid, lang=lang)

    async def _geocode_coords(self, lat: float, lon: float) -> Optional[Tuple[str, str, str]]:
        loop = asyncio.get_running_loop()
        def _fetch():
            url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "legacyProxy/0.9.2"})
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    addr = data.get("address", {})
                    city = addr.get("city") or addr.get("town") or addr.get("village") or "Lalín"
                    country = addr.get("country", "España")
                    region = addr.get("state", "Galicia")
                    return city, country, region
            except Exception:
                return None
        return await loop.run_in_executor(None, _fetch)

    async def _geocode_location(self, name: str) -> Optional[Tuple[float, float, str, str]]:
        loop = asyncio.get_running_loop()

        def _fetch():
            encoded = urllib.parse.quote(name)
            url = f"https://geocoding-api.open-meteo.com/v1/search?name={encoded}&count=1&language=es&format=json"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    results = data.get("results")
                    if results and len(results) > 0:
                        first = results[0]
                        return (
                            float(first["latitude"]),
                            float(first["longitude"]),
                            first.get("name", name),
                            first.get("country", "España"),
                        )
            except Exception as e:
                print(f"[WARN] Geocoding failed for {name}: {e}")
            return None

        return await loop.run_in_executor(None, _fetch)

    async def _fetch_open_meteo(self, lat: float, lon: float) -> dict:
        cache_key = f"{round(lat, 2)},{round(lon, 2)}"
        now = time.time()
        if cache_key in self._cache:
            cached_data, cached_time = self._cache[cache_key]
            if now - cached_time < 900:  # 15 min cache
                return cached_data

        loop = asyncio.get_running_loop()

        def _fetch():
            url = (
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                "&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,surface_pressure,wind_speed_10m,wind_direction_10m"
                "&daily=weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset"
                "&forecast_days=10"
                "&timezone=auto"
            )
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                print(f"[WARN] Open-Meteo fetch failed: {e}")
                return {}

        data = await loop.run_in_executor(None, _fetch)
        if data:
            self._cache[cache_key] = (data, now)
        return data

    def _build_channel_dict(
        self,
        weather: dict,
        lat: float,
        lon: float,
        city: str,
        country: str,
        region: str,
        woeid: int,
        lang: str = "es",
    ) -> dict:
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        pub_date = now_dt.strftime("%a, %d %b %Y %I:%M %p GMT")

        current = weather.get("current", {})
        temp_c = int(round(current.get("temperature_2m", 20.0)))
        apparent_c = int(round(current.get("apparent_temperature", temp_c)))
        wmo_code = current.get("weather_code", 0)
        humidity = int(round(current.get("relative_humidity_2m", 50)))
        wind_speed = int(round(current.get("wind_speed_10m", 10.0)))
        wind_dir = int(round(current.get("wind_direction_10m", 0.0)))
        pressure = round(current.get("surface_pressure", 1013.0), 1)

        yahoo_code, en_text, es_text = WMO_TO_YAHOO_MAP.get(wmo_code, (32, "Sunny", "Despejado"))
        condition_text = es_text if lang.startswith("es") else en_text

        daily = weather.get("daily", {})
        daily_times = daily.get("time", [])
        daily_maxs = daily.get("temperature_2m_max", [])
        daily_mins = daily.get("temperature_2m_min", [])
        daily_codes = daily.get("weather_code", [])
        daily_sunrises = daily.get("sunrise", [])
        daily_sunsets = daily.get("sunset", [])

        # Daily Forecasts (up to 10 days)
        forecast_list = []
        for i in range(min(len(daily_times), 10)):
            d_time_str = daily_times[i]
            d_high = int(round(daily_maxs[i])) if i < len(daily_maxs) else temp_c
            d_low = int(round(daily_mins[i])) if i < len(daily_mins) else temp_c - 5
            d_code = daily_codes[i] if i < len(daily_codes) else 0
            d_ycode, d_en, d_es = WMO_TO_YAHOO_MAP.get(d_code, (32, "Sunny", "Despejado"))
            d_text = d_es if lang.startswith("es") else d_en

            try:
                dt_obj = datetime.date.fromisoformat(d_time_str)
                d_day = SPANISH_DAYS[dt_obj.weekday()] if lang.startswith("es") else ENGLISH_DAYS[dt_obj.weekday()]
                d_date_str = dt_obj.strftime("%d %b %Y")
            except Exception:
                d_day = "Hoy"
                d_date_str = pub_date

            forecast_list.append(
                {
                    "code": str(d_ycode),
                    "date": d_date_str,
                    "day": d_day,
                    "high": str(d_high),
                    "low": str(d_low),
                    "text": d_text,
                }
            )

        sunrise_str = "07:00 am"
        sunset_str = "08:00 pm"
        if daily_sunrises and len(daily_sunrises) > 0:
            try:
                sr_dt = datetime.datetime.fromisoformat(daily_sunrises[0])
                sunrise_str = sr_dt.strftime("%I:%M %p").lower()
            except Exception:
                pass
        if daily_sunsets and len(daily_sunsets) > 0:
            try:
                ss_dt = datetime.datetime.fromisoformat(daily_sunsets[0])
                sunset_str = ss_dt.strftime("%I:%M %p").lower()
            except Exception:
                pass

        channel_dict = {
            "units": {
                "distance": "km",
                "pressure": "mb",
                "speed": "km/h",
                "temperature": "C",
            },
            "title": f"Yahoo! Weather - {city}",
            "link": "https://weather.yahoo.com",
            "description": f"Yahoo! Weather for {city}",
            "language": "es" if lang.startswith("es") else "en-us",
            "lastBuildDate": pub_date,
            "ttl": "60",
            "location": {
                "city": city,
                "country": country,
                "region": region,
                "woeid": str(woeid),
            },
            "wind": {
                "chill": str(apparent_c),
                "direction": str(wind_dir),
                "speed": str(wind_speed),
            },
            "atmosphere": {
                "humidity": str(humidity),
                "pressure": str(pressure),
                "rising": "0",
                "visibility": "10.0",
            },
            "astronomy": {
                "sunrise": sunrise_str,
                "sunset": sunset_str,
            },
            "image": {
                "title": "Yahoo! Weather",
                "width": "142",
                "height": "18",
                "link": "https://weather.yahoo.com",
                "url": "http://l.yimg.com/a/i/brand/purplelogo//uh/us/news-wea.gif",
            },
            "item": {
                "title": f"Conditions for {city} at {pub_date}",
                "lat": str(lat),
                "long": str(lon),
                "link": "https://weather.yahoo.com",
                "pubDate": pub_date,
                "condition": {
                    "code": str(yahoo_code),
                    "date": pub_date,
                    "temp": str(temp_c),
                    "text": condition_text,
                },
                "forecast": forecast_list,
                "guid": {"isPermaLink": "false"},
            },
        }
        return channel_dict

    def _format_yahoo_geo_response(self, city: str, country: str, lat: float, lon: float) -> str:
        now_date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        response_dict = {
            "query": {
                "count": 1,
                "created": now_date_str,
                "lang": "es",
                "results": {
                    "place": {
                        "woeid": "766273",
                        "name": city,
                        "country": {"content": country or "España", "code": "ES"},
                        "admin1": {"content": city, "code": ""},
                        "centroid": {"latitude": str(lat), "longitude": str(lon)},
                    }
                },
            }
        }
        return json.dumps(response_dict)

    def _format_yahoo_yql_response(
        self,
        weather: dict,
        lat: float,
        lon: float,
        city: str,
        country: str,
        region: str,
        woeid: int = 766273,
        lang: str = "en",
    ) -> str:
        channel_dict = self._build_channel_dict(weather, lat, lon, city, country, region, woeid, lang=lang)
        now_date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        response_dict = {
            "query": {
                "count": 1,
                "created": now_date_str,
                "lang": lang,
                "results": {
                    "channel": channel_dict
                },
            }
        }
        return json.dumps(response_dict)
