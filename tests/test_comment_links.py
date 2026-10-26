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

    def test_slow_container_within_300s_matches(self):
        # 2026-10-24 case: Instagram timestamp 90.4 s before the queue's posted_at
        r = cl.match([{"id": "m1", "timestamp": "2026-10-01T09:58:35+0000"}], QUEUE, {"a": "VIDA"})[0]
        self.assertEqual((r["slug"], r["vid"]), ("a", "VIDA"))
        r = cl.match([{"id": "m1", "timestamp": "2026-10-01T09:55:04+0000"}], QUEUE, {"a": "VIDA"})[0]
        self.assertIsNone(r["slug"])  # 301 s: still outside

    def test_unmatched_lists_only_engine_era_reels(self):
        media = [
            {"id": "old", "timestamp": "2026-09-01T10:00:00+0000", "media_product_type": "REELS", "permalink": "p/old"},
            {"id": "m1", "timestamp": "2026-10-01T10:00:00+0000", "media_product_type": "REELS", "permalink": "p/m1"},
            {"id": "lost", "timestamp": "2026-10-01T10:30:00+0000", "media_product_type": "REELS", "permalink": "p/lost"},
            {"id": "feed", "timestamp": "2026-10-01T11:00:00+0000", "media_product_type": "FEED", "permalink": "p/feed"},
        ]
        rows = cl.match(media, QUEUE, {"a": "VIDA"})
        u = cl.unmatched(rows, QUEUE)
        self.assertEqual(list(u), ["lost"])
        self.assertEqual(u["lost"]["permalink"], "p/lost")
        self.assertEqual(u["lost"]["nearest_delta"], 1620)
        self.assertEqual(cl.unmatched(rows, [{"id": "c", "posted_at": {}}]), {})

    def test_known_slug_without_youtube_id_has_no_vid(self):
        r = cl.match([{"id": "m1", "timestamp": "2026-10-01T10:00:00+0000"}], QUEUE, {})[0]
        self.assertEqual(r["slug"], "a")
        self.assertIsNone(r["vid"])


if __name__ == "__main__":
    unittest.main()
