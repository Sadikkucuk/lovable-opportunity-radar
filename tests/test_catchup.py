"""Regression tests for a delayed, full-size same-day RSS feed."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from radar.engine import Engine


class DelayedFeedCatchupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.e = Engine(Path(self.temp.name), datetime(2026, 10, 12, 21, 10, tzinfo=timezone.utc))
        self.e.write("state/v2/config.json", {"mode": "active", "shared_queue": True})

    @staticmethod
    def articles(ids):
        return [{"id": str(i), "url": f"https://example.org/news/{i}", "title": f"Article {i}"} for i in ids]

    def test_late_feed_adds_only_unsnapshotted_urls_without_touching_daily(self):
        # 00:10 Istanbul daily run freezes the older feed.
        self.e.write("docs/latest.json", {"generated_at": "2026-10-12T20:30:00Z",
                                          "items": self.articles([0, 1, 2])})
        self.e.create_run("a" * 40)
        daily_path = self.e.paths("state/v2/runs/*/snapshot.json")[0]
        original_bytes = (self.e.root / daily_path).read_bytes()
        # Feed collector finishes much later on the same Istanbul calendar day.
        self.e.now = datetime(2026, 10, 13, 2, 20, tzinfo=timezone.utc)
        self.e.write("docs/latest.json", {"generated_at": "2026-10-13T02:13:00Z",
                                          "items": self.articles([1, 2] + list(range(3, 25)))})
        self.e.create_catchup_run("b" * 40)
        manifests = [self.e.read(p) for p in self.e.paths("state/v2/runs/*/manifest.json")]
        self.assertEqual(len(manifests), 2)
        catchup = next(m for m in manifests if m["kind"] == "catchup")
        self.assertEqual(catchup["unique_count"], 22)
        self.assertEqual(catchup["overlap_count"], 2)
        self.assertEqual(catchup["previously_snapshotted_count"], 3)
        self.assertEqual(sorted(len(self.e.read(f"state/v2/jobs/{x}.json")["payload"]["articles"])
                                for x in catchup["initial_jobs"]), [2, 10, 10])
        self.assertEqual((self.e.root / daily_path).read_bytes(), original_bytes)
        before_jobs = set(self.e.jobs())
        self.e.create_catchup_run("c" * 40)
        self.assertEqual(set(self.e.jobs()), before_jobs)
        self.assertEqual(len(self.e.paths("state/v2/runs/*/manifest.json")), 2)

    def test_changed_feed_same_urls_does_not_repeat_research(self):
        self.e.write("docs/latest.json", {"generated_at": "2026-10-12T20:30:00Z",
                                          "items": self.articles([1])})
        self.e.create_run("a" * 40)
        self.e.now = datetime(2026, 10, 13, 2, 20, tzinfo=timezone.utc)
        self.e.write("docs/latest.json", {"generated_at": "2026-10-13T02:13:00Z",
                                          "items": self.articles([1, 2])})
        self.e.create_catchup_run("b" * 40)
        self.e.now = datetime(2026, 10, 13, 2, 40, tzinfo=timezone.utc)
        self.e.write("docs/latest.json", {"generated_at": "2026-10-13T02:35:00Z",
                                          "items": self.articles([2, 1, 3])})
        self.e.create_catchup_run("c" * 40)
        catches = [self.e.read(p) for p in self.e.paths("state/v2/runs/*/manifest.json")
                   if self.e.read(p)["kind"] == "catchup"]
        self.assertEqual(sorted(m["unique_count"] for m in catches), [1, 1])
        self.assertEqual(sum(m["unique_count"] for m in catches), 2)

    def test_different_day_or_older_feed_cannot_create_catchup(self):
        self.e.write("docs/latest.json", {"generated_at": "2026-10-12T20:30:00Z",
                                          "items": self.articles([1])})
        self.e.create_run("a" * 40)
        self.e.now = datetime(2026, 10, 13, 2, 20, tzinfo=timezone.utc)
        for generation in ("2026-10-12T20:40:00Z", "2026-10-12T21:00:00Z",
                           "2026-10-14T01:00:00Z", "invalid-date"):
            self.e.write("docs/latest.json", {"generated_at": generation,
                                              "items": self.articles([2])})
            self.e.create_catchup_run("b" * 40)
        self.assertEqual(len(self.e.paths("state/v2/runs/*/manifest.json")), 1)


if __name__ == "__main__":
    unittest.main()
