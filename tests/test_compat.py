import unittest
from types import SimpleNamespace
from unittest.mock import patch
import src.compat as compat
from src.compat.css import adapt_css
from src.compat.html import adapt_html
from src.compat.js import adapt_js, analyze_js
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
            adapt_html(html,target=LegacyTarget(8)),
            '<img src="new.jpg"><img src="fallback.jpg">',
        )

    def test_adapt_css_preserves_current_transformations(self):
        css = ".card { display: flex; justify-content: start; transform: scale(1); }"
        self.assertEqual(
            adapt_css(css,target=LegacyTarget(8)),
            ".card { display: -webkit-flex; display: flex; "
            "-webkit-justify-content: flex-start; justify-content: flex-start; "
            "-webkit-transform: scale(1); transform: scale(1); }",
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

    def test_adapt_js_is_passthrough(self):
        source = "const value = item => item?.value ?? null;"
        self.assertEqual(adapt_js(source,target=LegacyTarget(9)), source)

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
            9: features - {"promise", "object-assign", "array-from"},
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
            ),
        )

        with patch("main.compat.analyze_js", return_value={"arrow-functions", "const", "fetch"}) as analyze:
            with patch("main.compat.adapt_js", return_value="adapted") as adapter:
                with patch("builtins.print") as output:
                    addon.response(flow)

        analyze.assert_called_once_with("const fn = item => fetch(item);")
        adapter.assert_called_once_with(
            "const fn = item => fetch(item);",target=LegacyTarget(9))
        self.assertEqual(flow.response.text, "adapted")
        compat_logs = [
            call.args[0] for call in output.call_args_list
            if call.args and call.args[0].startswith("[COMPAT] unsupported JS")
        ]
        self.assertEqual(
            compat_logs,
            ["[COMPAT] unsupported JS=arrow-functions,const,fetch target=iOS 9"],
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


if __name__ == "__main__":
    unittest.main()
