import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import comment_links as cl  # noqa: E402

QUEUE = [
    {"id": "a", "posted_at": {"instagram": "2026-10-01T10:00:05+00:00"}},
    {"id": "b", "posted_at": {"instagram": "2026-10-01T10:03:00+00:00"}},
    {"id": "c", "posted_at": {}},
]


class Match(unittest.TestCase):
    def test_exact_within_guard_matches_and_reports_delta(self):
        r = cl.match([{"id": "m1", "timestamp": "2026-10-01T10:00:00+0000"}], QUEUE, {"a": "VIDA"})[0]
        self.assertEqual((r["slug"], r["vid"], round(r["delta"])), ("a", "VIDA", 5))

    def test_outside_guard_is_no_match(self):
        r = cl.match([{"id": "m1", "timestamp": "2026-10-01T10:10:00+0000"}], QUEUE, {"a": "VIDA", "b": "VIDB"})[0]
        self.assertIsNone(r["slug"])
        self.assertIsNone(r["vid"])

    def test_nearest_of_two_close_posts_wins(self):
        r = cl.match([{"id": "m2", "timestamp": "2026-10-01T10:03:02+0000"}], QUEUE, {"a": "VIDA", "b": "VIDB"})[0]
        self.assertEqual(r["slug"], "b")

    def test_known_slug_without_youtube_id_has_no_vid(self):
        r = cl.match([{"id": "m1", "timestamp": "2026-10-01T10:00:00+0000"}], QUEUE, {})[0]
        self.assertEqual(r["slug"], "a")
        self.assertIsNone(r["vid"])


if __name__ == "__main__":
    unittest.main()
