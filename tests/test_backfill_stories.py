import datetime
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import backfill_stories as bs  # noqa: E402

NOW = datetime.datetime(2026, 10, 14, 12, 0, tzinfo=datetime.timezone.utc)


def iso(hours_ago):
    return (NOW - datetime.timedelta(hours=hours_ago)).isoformat()


QUEUE = [
    {"id": "old", "media_type": "video", "media_url": "u/old", "posted_at": {"facebook": iso(30)}},
    {"id": "b", "media_type": "video", "media_url": "u/b", "posted_at": {"facebook": iso(5), "instagram": iso(5)}},
    {"id": "a", "media_type": "video", "media_url": "u/a", "posted_at": {"facebook": iso(20)}},
    {"id": "photo", "media_type": "photo", "media_url": "u/p", "posted_at": {"facebook": iso(1)}},
    {"id": "unposted", "media_type": "video", "media_url": "u/x", "posted_at": {}},
    {"id": "c", "media_type": "video", "media_url": "u/c", "posted_at": {"facebook": iso(2)}},
]


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.q = os.path.join(self.dir, "q.json")
        self.s = os.path.join(self.dir, "s.json")
        json.dump(QUEUE, open(self.q, "w"))

    def test_pick_window_order_and_platform(self):
        ids = [i["id"] for i in bs.pick_eligible(QUEUE, {}, "facebook", 24, NOW)]
        self.assertEqual(ids, ["a", "b", "c"])
        ids = [i["id"] for i in bs.pick_eligible(QUEUE, {}, "facebook", 72, NOW)]
        self.assertEqual(ids, ["old", "a", "b", "c"])
        self.assertEqual([i["id"] for i in bs.pick_eligible(QUEUE, {}, "instagram", 24, NOW)], ["b"])

    def test_state_skips_done(self):
        ids = [i["id"] for i in bs.pick_eligible(QUEUE, {"facebook": ["a"]}, "facebook", 24, NOW)]
        self.assertEqual(ids, ["b", "c"])

    def test_dry_run_writes_nothing_and_posts_nothing(self):
        calls = []
        bs.run("facebook", 24, 3, True, self.q, self.s, now=NOW, poster=lambda *a: calls.append(a))
        self.assertEqual(calls, [])
        self.assertFalse(os.path.exists(self.s))

    def test_limit_pause_and_state_recorded(self):
        calls, sleeps = [], []
        failures = bs.run("facebook", 24, 2, False, self.q, self.s, now=NOW,
                          sleep=sleeps.append, poster=lambda p, u: calls.append(u))
        self.assertEqual(failures, 0)
        self.assertEqual(calls, ["u/a", "u/b"])
        self.assertEqual(sleeps, [60])
        self.assertEqual(json.load(open(self.s)), {"facebook": ["a", "b"]})

    def test_failure_not_recorded_and_continues(self):
        def poster(p, u):
            if u == "u/a":
                raise RuntimeError("boom")
        failures = bs.run("facebook", 24, 3, False, self.q, self.s, now=NOW,
                          sleep=lambda s: None, poster=poster)
        self.assertEqual(failures, 1)
        self.assertEqual(json.load(open(self.s)), {"facebook": ["b", "c"]})


if __name__ == "__main__":
    unittest.main()
