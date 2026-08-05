"""Tests for the cross-run scratch-directory lock."""

import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import run_lock


class RunLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "locks")

    def tearDown(self):
        self.tmp.cleanup()

    def test_acquire_creates_lock_file_with_pid(self):
        payload = run_lock.acquire("longform", self.dir)
        self.assertTrue(os.path.isfile(run_lock.lock_path("longform", self.dir)))
        self.assertEqual(payload["pid"], os.getpid())
        self.assertEqual(run_lock.read_lock("longform", self.dir)["pid"], os.getpid())

    def test_second_acquire_is_refused_while_lock_is_live(self):
        run_lock.acquire("longform", self.dir)
        with self.assertRaises(run_lock.RunLockBusy):
            run_lock.acquire("longform", self.dir)

    def test_different_names_do_not_block_each_other(self):
        run_lock.acquire("longform", self.dir)
        run_lock.acquire("shorts", self.dir)  # must not raise

    def test_release_allows_a_later_run(self):
        payload = run_lock.acquire("longform", self.dir)
        run_lock.release("longform", self.dir, payload)
        self.assertFalse(os.path.isfile(run_lock.lock_path("longform", self.dir)))
        run_lock.acquire("longform", self.dir)  # must not raise

    def test_expired_lock_is_stolen(self):
        run_lock.acquire("longform", self.dir, ttl_seconds=60)
        # Backdate the holder past its TTL, as a crashed run would leave it.
        path = run_lock.lock_path("longform", self.dir)
        with open(path, encoding="utf-8") as handle:
            holder = json.load(handle)
        holder["started_at"] = time.time() - 3600
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(holder, handle)

        payload = run_lock.acquire("longform", self.dir, ttl_seconds=60)
        self.assertEqual(payload["pid"], os.getpid())

    def test_unreadable_lock_is_treated_as_stale(self):
        os.makedirs(self.dir, exist_ok=True)
        with open(run_lock.lock_path("longform", self.dir), "w", encoding="utf-8") as handle:
            handle.write("not json at all")
        run_lock.acquire("longform", self.dir)  # must not raise

    def test_release_does_not_delete_a_newer_runs_lock(self):
        stale_payload = run_lock.acquire("longform", self.dir, ttl_seconds=1)
        time.sleep(1.1)
        newer_payload = run_lock.acquire("longform", self.dir, ttl_seconds=1)

        # The superseded run finishing must not free the live run's lock.
        run_lock.release("longform", self.dir, stale_payload)
        self.assertEqual(
            run_lock.read_lock("longform", self.dir)["started_at"],
            newer_payload["started_at"],
        )

    def test_busy_error_names_the_holder(self):
        run_lock.acquire("longform", self.dir)
        with self.assertRaises(run_lock.RunLockBusy) as caught:
            run_lock.acquire("longform", self.dir)
        self.assertIn("longform", str(caught.exception))
        self.assertIn(str(os.getpid()), str(caught.exception))

    def test_context_manager_releases_on_exception(self):
        with self.assertRaises(ValueError):
            with run_lock.run_lock("longform", self.dir):
                raise ValueError("boom")
        self.assertFalse(os.path.isfile(run_lock.lock_path("longform", self.dir)))

    def test_is_stale_respects_ttl_boundary(self):
        now = 1_000_000.0
        self.assertFalse(run_lock.is_stale({"started_at": now - 59}, 60, now=now))
        self.assertTrue(run_lock.is_stale({"started_at": now - 60}, 60, now=now))
        self.assertTrue(run_lock.is_stale({}, 60, now=now))


if __name__ == "__main__":
    unittest.main()
