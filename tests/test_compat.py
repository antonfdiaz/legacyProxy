import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import src.compat as compat
from src.compat.css import adapt_css
from src.compat.html import adapt_html
from src.compat.js import adapt_js, analyze_js
from src.compat.runtime import required_polyfills
from src.compat import js as js_module
from src.compat.target import LegacyTarget, detect_target, unsupported_js_features
from main import InterceptAddon


class CompatibilityTests(unittest.TestCase):
    def test_public_adapters_are_reexported(self):
        self.assertIs(compat.adapt_html, adapt_html)
        self.assertIs(compat.adapt_css, adapt_css)
        self.assertIs(compat.adapt_js, adapt_js)
        self.assertIs(compat.analyze_js, analyze_js)

    def test_adapt_html_preserves_current_transformations(self):
        html = (
            '<img loading="lazy" src="old.jpg" data-src="new.jpg" inert>'
            '<picture><source srcset="new.webp"><img src="fallback.jpg"></picture>'
        )
        self.assertEqual(
            adapt_html(html,target=LegacyTarget(13)),
            '<img src="new.jpg"><img src="fallback.jpg">',
        )

    def test_adapt_html_injects_fetch_polyfill_for_ios9(self):
        html = "<html><head><title>Page</title></head><body></body></html>"
        with patch("builtins.print") as output:
            adapted = adapt_html(html,target=LegacyTarget(9))
        marker = 'id="legacy-proxy-polyfill-fetch"'
        for feature in (
            "fetch", "object-entries", "object-values", "object-from-entries",
            "url-search-params",
        ):
            self.assertEqual(
                adapted.count(f'id="legacy-proxy-polyfill-{feature}"'),
                1,
            )
        self.assertLess(adapted.index(marker), adapted.index("</head>"))
        self.assertIn("XMLHttpRequest", adapted)
        logs = [call.args[0] for call in output.call_args_list]
        self.assertEqual(
            logs,
            [
                "[COMPAT] injecting polyfill=fetch target=iOS 9",
                "[COMPAT] injecting polyfill=object-entries target=iOS 9",
                "[COMPAT] injecting polyfill=object-values target=iOS 9",
                "[COMPAT] injecting polyfill=object-from-entries target=iOS 9",
                "[COMPAT] injecting polyfill=url-search-params target=iOS 9",
            ],
        )

    def test_adapt_html_injects_fetch_polyfill_before_external_scripts(self):
        html = '<html><head><script src="/app.js"></script></head></html>'
        adapted = adapt_html(html,target=LegacyTarget(9))
        original_script = adapted.index('<script src="/app.js">')
        for feature in (
            "fetch", "object-entries", "object-values", "object-from-entries",
            "url-search-params",
        ):
            self.assertLess(
                adapted.index(f'id="legacy-proxy-polyfill-{feature}"'),
                original_script,
            )

    def test_adapt_html_injects_only_unsupported_polyfills_for_ios10(self):
        html = "<html><script>fetch('/data');</script></html>"
        adapted = adapt_html(html,target=LegacyTarget(10))
        self.assertNotIn("legacy-proxy-polyfill-fetch", adapted)
        self.assertNotIn("legacy-proxy-polyfill-object-entries", adapted)
        self.assertNotIn("legacy-proxy-polyfill-object-values", adapted)
        self.assertIn("legacy-proxy-polyfill-object-from-entries", adapted)
        self.assertNotIn("legacy-proxy-polyfill-url-search-params", adapted)

    def test_adapt_html_injects_without_inline_fetch(self):
        html = "<html><script>Promise.resolve('ready');</script></html>"
        self.assertIn(
            "legacy-proxy-polyfill-fetch",
            adapt_html(html,target=LegacyTarget(9)),
        )

    def test_adapt_html_does_not_duplicate_fetch_polyfill(self):
        html = "<html><script>fetch('/data');</script></html>"
        with patch("builtins.print") as output:
            adapted = adapt_html(html,target=LegacyTarget(9))
            repeated = adapt_html(adapted,target=LegacyTarget(9))
        self.assertEqual(repeated, adapted)
        for feature in (
            "fetch", "object-entries", "object-values", "object-from-entries",
            "url-search-params",
        ):
            self.assertEqual(repeated.count(f"legacy-proxy-polyfill-{feature}"), 1)
        self.assertEqual(output.call_count, 5)

    def test_adapt_css_preserves_current_transformations(self):
        css = ".card { display: flex; justify-content: start; transform: scale(1); }"
        self.assertEqual(
            adapt_css(css,target=LegacyTarget(8)),
            ".card { display: -webkit-flex; display: flex; "
            "-webkit-justify-content: flex-start; justify-content: flex-start; "
            "-webkit-transform: scale(1); transform: scale(1); }",
        )

    def test_required_fetch_polyfill(self):
        self.assertEqual(
            required_polyfills(LegacyTarget(9),{"fetch"}),
            {"fetch"},
        )
        self.assertEqual(
            required_polyfills(LegacyTarget(10),{"fetch"}),
            set(),
        )
        self.assertEqual(
            required_polyfills(LegacyTarget(9),{"promise"}),
            set(),
        )

    def test_required_polyfills_by_target(self):
        features = {
            "fetch", "object-entries", "object-values", "object-from-entries",
            "url-search-params",
        }
        self.assertEqual(required_polyfills(LegacyTarget(9),features), features)
        self.assertEqual(
            required_polyfills(LegacyTarget(10),features),
            {"object-from-entries"},
        )
        self.assertEqual(required_polyfills(LegacyTarget(13),features), set())
        self.assertEqual(
            required_polyfills(
                LegacyTarget(9),
                {"array-includes", "element-closest", "mutation-observer"},
            ),
            set(),
        )


class TargetDetectionTests(unittest.TestCase):
    def test_detects_ios_major_version(self):
        cases = {
            "Mozilla/5.0 (iPhone; CPU iPhone OS 8_4_1 like Mac OS X)": 8,
            "Mozilla/5.0 (iPhone; CPU iPhone OS 6_1 like Mac OS X)": 6,
            "Reddit/2.0.1 (iOS 9.3.5)": 9,
        }
        for user_agent, expected_major in cases.items():
            with self.subTest(user_agent=user_agent):
                self.assertEqual(
                    detect_target(user_agent),
                    LegacyTarget(expected_major),
                )

    def test_unknown_target(self):
        self.assertEqual(
            detect_target("Mozilla/5.0 (Macintosh; Intel Mac OS X)"),
            LegacyTarget(None),
        )
        self.assertEqual(detect_target(None), LegacyTarget(None))


class JavaScriptCompatibilityTests(unittest.TestCase):
    def setUp(self):
        js_module._JS_CACHE.clear()

    def test_analyze_js_detects_supported_features(self):
        source = (
            "let value = 1; const fn = item => `value=${item}`; "
            "class Example {}; async function load() { await Promise.resolve(); } "
            "value?.name ?? 'unknown'; fetch('/data'); Object.assign({}, value); "
            "Array.from(value);"
        )
        self.assertEqual(
            analyze_js(source),
            {
                "let", "const", "arrow-functions", "class", "template-literals",
                "async", "await", "optional-chaining", "nullish-coalescing",
                "promise", "fetch", "object-assign", "array-from",
            },
        )

    def test_analyze_js_detects_runtime_and_dom_features_without_duplicates(self):
        source = (
            "Symbol(); new Map(); new Set(); new WeakMap(); new WeakSet(); "
            "new URL('/'); new URLSearchParams(); Object.entries({}); "
            "Object.values({}); Object.fromEntries([]); "
            "items.includes(value); text.includes('x'); text.startsWith('x'); "
            "text.endsWith('x'); element.closest('.item'); element.matches('.item'); "
            "new CustomEvent('ready'); new IntersectionObserver(fn); "
            "new MutationObserver(fn); items.includes(value);"
        )
        self.assertEqual(
            analyze_js(source) & compat.RUNTIME_FEATURES,
            {
                "symbol", "map", "set", "weakmap", "weakset", "url",
                "url-search-params", "object-entries", "object-values",
                "object-from-entries", "array-includes", "string-includes",
                "string-starts-with", "string-ends-with", "element-closest",
                "element-matches", "custom-event", "intersection-observer",
                "mutation-observer",
            },
        )

    def test_adapt_js_is_passthrough(self):
        source = "Promise.resolve(Object.assign({}, Array.from([])));"
        self.assertEqual(adapt_js(source,target=LegacyTarget(9)), source)

    def test_adapt_js_transpiles_modern_syntax_for_ios9(self):
        source = "const add = (left, right) => left + right;"
        adapted = adapt_js(source,target=LegacyTarget(9))
        self.assertNotEqual(adapted, source)
        self.assertNotIn("const", adapted)
        self.assertNotIn("=>", adapted)
        self.assertNotIn("core-js", adapted)

    def test_adapt_js_target_none_is_unchanged(self):
        source = "const value = item => item?.value ?? null;"
        self.assertEqual(adapt_js(source), source)

    def test_adapt_js_failure_returns_original_source(self):
        source = "const value = item => item;"
        with patch("src.compat.js.subprocess.run", side_effect=OSError("node missing")):
            with patch("builtins.print") as output:
                adapted = adapt_js(source,target=LegacyTarget(9))
        self.assertEqual(adapted, source)
        self.assertIn(
            "[WARN] JS transpilation failed: node missing",
            output.call_args[0][0],
        )

    def test_js_cache_miss_runs_babel(self):
        source = "const value = item => item;"
        result = SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps({"code": "transpiled"}),
        )
        with patch("src.compat.js.subprocess.run", return_value=result) as run:
            self.assertEqual(adapt_js(source,target=LegacyTarget(9)), "transpiled")
        run.assert_called_once()

    def test_second_identical_call_uses_js_cache(self):
        source = "const value = item => item;"
        result = SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps({"code": source}),
        )
        with patch("src.compat.js.subprocess.run", return_value=result) as run:
            with patch("builtins.print") as output:
                self.assertEqual(adapt_js(source,target=LegacyTarget(9)), source)
                self.assertEqual(adapt_js(source,target=LegacyTarget(9)), source)
        run.assert_called_once()
        self.assertIn(
            "[COMPAT] JS cache hit target=iOS 9",
            output.call_args[0][0],
        )

    def test_same_source_with_different_targets_has_different_cache_entries(self):
        source = "const value = item => item;"
        result = SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps({"code": "transpiled"}),
        )
        with patch("src.compat.js.subprocess.run", return_value=result) as run:
            adapt_js(source,target=LegacyTarget(8))
            adapt_js(source,target=LegacyTarget(9))
        self.assertEqual(run.call_count, 2)

    def test_failed_babel_run_is_not_cached(self):
        source = "const value = item => item;"
        with patch(
            "src.compat.js.subprocess.run",
            side_effect=OSError("node missing"),
        ) as run:
            with patch("builtins.print"):
                self.assertEqual(adapt_js(source,target=LegacyTarget(9)), source)
                self.assertEqual(adapt_js(source,target=LegacyTarget(9)), source)
        self.assertEqual(run.call_count, 2)

    def test_unsupported_features_by_ios_major(self):
        features = {
            "let", "const", "arrow-functions", "class", "template-literals",
            "async", "await", "optional-chaining", "nullish-coalescing",
            "promise", "fetch", "object-assign", "array-from",
        }
        expected = {
            3: features,
            4: features,
            5: features,
            6: features,
            7: features,
            8: features - {"promise", "object-assign"},
            9: features - {"class", "template-literals", "promise", "object-assign", "array-from"},
        }
        for ios_major, unsupported in expected.items():
            with self.subTest(ios_major=ios_major):
                self.assertEqual(
                    unsupported_js_features(LegacyTarget(ios_major),features),
                    unsupported,
                )

    def test_unknown_features_and_non_ios_target_are_not_unsupported(self):
        self.assertEqual(
            unsupported_js_features(
                LegacyTarget(9),{"promise", "not-in-the-table"}),
            set(),
        )
        self.assertEqual(
            unsupported_js_features(LegacyTarget(None),{"async", "fetch"}),
            set(),
        )


class CompatibilityPipelineTests(unittest.TestCase):
    def test_main_passes_ios_target_and_logs_it(self):
        addon = InterceptAddon.__new__(InterceptAddon)
        addon.github = None
        addon.wikipedia = None
        addon.reddit = None
        addon.imdb = None
        flow = SimpleNamespace(
            request=SimpleNamespace(
                url="https://example.test/page",
                headers={
                    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 8_4_1 like Mac OS X)"
                },
            ),
            response=SimpleNamespace(
                headers={"Content-Type": "text/html; charset=utf-8"},
                text="<html></html>",
            ),
        )

        with patch("main.compat.adapt_html", return_value="adapted") as adapter:
            with patch("builtins.print") as output:
                addon.response(flow)

        adapter.assert_called_once_with(
            "<html></html>",target=LegacyTarget(8))
        self.assertEqual(flow.response.text, "adapted")
        log = "\n".join(call.args[0] for call in output.call_args_list)
        self.assertIn("[COMPAT] target=iOS 8", log)

    def test_main_analyzes_and_passes_javascript_target(self):
        addon = InterceptAddon.__new__(InterceptAddon)
        addon.github = None
        addon.wikipedia = None
        addon.reddit = None
        addon.imdb = None
        flow = SimpleNamespace(
            request=SimpleNamespace(
                url="https://example.test/script.js",
                headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 9_3 like Mac OS X)"},
            ),
            response=SimpleNamespace(
                headers={"Content-Type": "application/javascript; charset=utf-8"},
                text="const fn = item => fetch(item);",
                status_code=200,
            ),
        )

        with patch("main.compat.analyze_js", return_value={"arrow-functions", "const", "fetch"}) as analyze:
            with patch("main.compat.adapt_js", return_value="transpiled") as adapter:
                with patch("builtins.print") as output:
                    addon.response(flow)

        analyze.assert_called_once_with("const fn = item => fetch(item);")
        adapter.assert_called_once_with(
            "const fn = item => fetch(item);",target=LegacyTarget(9))
        self.assertEqual(flow.response.text, "transpiled")
        compat_logs = [
            call.args[0] for call in output.call_args_list
            if call.args and call.args[0].startswith("[COMPAT]")
        ]
        self.assertEqual(
            compat_logs,
            [
                "[COMPAT] runtime JS=fetch",
                "[COMPAT] unsupported JS=arrow-functions,const,fetch target=iOS 9",
                "[COMPAT] transpiled JS target=iOS 9",
            ],
        )

    def test_main_skips_javascript_for_excluded_hosts(self):
        addon = InterceptAddon.__new__(InterceptAddon)
        addon.github = None
        addon.wikipedia = None
        addon.reddit = None
        addon.imdb = None
        flow = SimpleNamespace(
            request=SimpleNamespace(
                url="https://token.awswaf.com/script.js",
                headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 9_3 like Mac OS X)"},
            ),
            response=SimpleNamespace(
                headers={"Content-Type": "text/javascript"},
                text="const value = 1;",
            ),
        )

        with patch("main.compat.analyze_js") as analyze:
            with patch("main.compat.adapt_js") as adapter:
                addon.response(flow)

        analyze.assert_not_called()
        adapter.assert_not_called()

    def test_main_logs_runtime_features_not_in_support_matrix(self):
        addon = InterceptAddon.__new__(InterceptAddon)
        addon.github = None
        addon.wikipedia = None
        addon.reddit = None
        addon.imdb = None
        flow = SimpleNamespace(
            request=SimpleNamespace(
                url="https://example.test/script.js",
                headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 9_3 like Mac OS X)"},
            ),
            response=SimpleNamespace(
                headers={"Content-Type": "application/javascript"},
                text="new Map(); new IntersectionObserver(fn);",
                status_code=200,
            ),
        )

        with patch(
            "main.compat.analyze_js",
                return_value={"map", "intersection-observer"},
        ) as analyze:
            with patch("main.compat.adapt_js", return_value=flow.response.text):
                with patch("builtins.print") as output:
                    addon.response(flow)

            analyze.assert_called_once_with("new Map(); new IntersectionObserver(fn);")
        compat_logs = [
            call.args[0] for call in output.call_args_list
            if call.args and call.args[0].startswith("[COMPAT]")
        ]
        self.assertEqual(
            compat_logs,
            ["[COMPAT] runtime JS=intersection-observer,map"],
        )

    def test_main_does_not_analyze_empty_or_no_content_javascript(self):
        addon = InterceptAddon.__new__(InterceptAddon)
        addon.github = None
        addon.wikipedia = None
        addon.reddit = None
        addon.imdb = None
        for status_code, text in ((204,"const value = 1;"),(304,"const value = 1;"),(200,"")):
            flow = SimpleNamespace(
                request=SimpleNamespace(
                    url="https://example.test/script.js",
                    headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 9_3 like Mac OS X)"},
                ),
                response=SimpleNamespace(
                    headers={"Content-Type": "application/javascript"},
                    text=text,
                    status_code=status_code,
                ),
            )
            with patch("main.compat.analyze_js") as analyze:
                with patch("main.compat.adapt_js") as adapter:
                    addon.response(flow)
            analyze.assert_not_called()
            adapter.assert_not_called()


class RequestCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_clears_cache_headers_for_script_paths(self):
        addon = InterceptAddon.__new__(InterceptAddon)
        addon.google = None
        addon.imdb = None
        addon.reddit = None
        addon.wikipedia = None
        for path in ("/style.css", "/page.html", "/page.htm", "/script.js", "/module.mjs"):
            flow = SimpleNamespace(
                request=SimpleNamespace(
                    url=f"https://example.test{path}?v=1",
                    headers={"If-None-Match": "etag", "If-Modified-Since": "yesterday"},
                ),
            )
            await addon.request(flow)
            with self.subTest(path=path):
                self.assertNotIn("If-None-Match", flow.request.headers)
                self.assertNotIn("If-Modified-Since", flow.request.headers)


if __name__ == "__main__":
    unittest.main()
