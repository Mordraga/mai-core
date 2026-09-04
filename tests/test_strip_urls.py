import unittest

from daemons.commands_daemon import _strip_urls


class StripUrlsAndIpsTests(unittest.TestCase):
    def test_strips_http_url(self):
        self.assertEqual(_strip_urls("Check this out: https://example.com/page"), "Check this out:")

    def test_strips_bare_domain(self):
        self.assertEqual(_strip_urls("Find me at discord.gg/abc123 sometime"), "Find me at sometime")

    def test_strips_ipv4_address(self):
        self.assertEqual(_strip_urls("My server lives at 10.0.0.5 always"), "My server lives at always")

    def test_strips_leaked_ipv4_from_real_incident(self):
        raw = "192.168.1.1, and no, I shouldn't use mine as an example."
        self.assertEqual(_strip_urls(raw), "and no, I shouldn't use mine as an example.")

    def test_ipv4_octet_bounds_avoid_false_positive_on_version_strings(self):
        # 2024 exceeds a valid IPv4 octet (0-255), so this should NOT be
        # treated as an address and stripped.
        raw = "Version 3.10.2024.5 released today."
        self.assertEqual(_strip_urls(raw), raw)

    def test_leaves_ordinary_message_untouched(self):
        raw = "normal message with no ip or url"
        self.assertEqual(_strip_urls(raw), raw)

    def test_strips_full_form_ipv6(self):
        raw = "reach me at 2001:0db8:85a3:0000:0000:8a2e:0370:7334 tonight"
        self.assertEqual(_strip_urls(raw), "reach me at tonight")


if __name__ == "__main__":
    unittest.main()
