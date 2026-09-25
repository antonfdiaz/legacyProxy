import unittest
from types import SimpleNamespace
from unittest.mock import patch
import src.compat as compat
from src.compat.css import adapt_css
from src.compat.html import adapt_html
from src.compat.target import LegacyTarget, detect_target
from main import InterceptAddon


class CompatibilityTests(unittest.TestCase):
    def test_public_adapters_are_reexported(self):
        self.assertIs(compat.adapt_html, adapt_html)
        self.assertIs(compat.adapt_css, adapt_css)

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


if __name__ == "__main__":
    unittest.main()
