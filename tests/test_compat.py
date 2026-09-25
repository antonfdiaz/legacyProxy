import unittest

import src.compat as compat
from src.compat.css import adapt_css
from src.compat.html import adapt_html
from src.compat.target import LegacyTarget, detect_target


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
            adapt_html(html),
            '<img src="new.jpg"><img src="fallback.jpg">',
        )

    def test_adapt_css_preserves_current_transformations(self):
        css = ".card { display: flex; justify-content: start; transform: scale(1); }"
        self.assertEqual(
            adapt_css(css),
            ".card { display: -webkit-flex; display: flex; "
            "-webkit-justify-content: flex-start; justify-content: flex-start; "
            "-webkit-transform: scale(1); transform: scale(1); }",
        )


class TargetDetectionTests(unittest.TestCase):
    def test_detects_ios_target_buckets(self):
        cases = {
            3: "ios_3_4",
            4: "ios_3_4",
            5: "ios_5_6",
            6: "ios_5_6",
            7: "ios_7",
            8: "ios_8_plus",
            17: "ios_8_plus",
        }
        for version, expected_name in cases.items():
            user_agent = (
                "Mozilla/5.0 (iPhone; CPU iPhone OS "
                f"{version}_0 like Mac OS X) AppleWebKit/605.1.15"
            )
            with self.subTest(version=version):
                self.assertEqual(detect_target(user_agent).name, expected_name)

    def test_detects_explicit_ios_app_user_agent(self):
        self.assertEqual(
            detect_target("Reddit/2.0.1 (iOS 8.4.1)").name,
            "ios_8_plus",
        )

    def test_unknown_target(self):
        self.assertEqual(detect_target("Mozilla/5.0 (Macintosh; Intel Mac OS X)"), LegacyTarget("unknown"))
        self.assertEqual(detect_target(None), LegacyTarget("unknown"))


if __name__ == "__main__":
    unittest.main()
