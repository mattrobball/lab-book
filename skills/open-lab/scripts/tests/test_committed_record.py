"""The record is what is committed. A git checkout, stash or reset on the
working tree must not roll a run back to open or a claim back to proposed
(R-038 was ingested twice on 2026-09-02 after exactly that)."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import claims
import run


def sh(root, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@x", *args],
                   cwd=root, check=True, capture_output=True)


class CommittedRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        sh(self.root, "init", "-q")
        self.problem = self.root / "problems" / "p"
        (self.problem / "runs" / "R-001").mkdir(parents=True)
        (self.problem / "claims").mkdir()
        claims.forget_committed()
        claims._ROOTS.clear()

    def tearDown(self):
        claims.forget_committed()
        claims._ROOTS.clear()
        self.tmp.cleanup()

    def commit_all(self, msg):
        sh(self.root, "add", "-A")
        sh(self.root, "commit", "-q", "--allow-empty", "-m", msg)
        claims.forget_committed()

    def test_rolled_back_dispatch_still_reads_as_ingested(self):
        p = self.problem / "runs" / "R-001" / "dispatch.json"
        p.write_text(json.dumps({"run": "R-001", "status": "ingested",
                                 "verdict": "PASS", "ingested_at": "t"}))
        self.commit_all("R-001 ingested")
        p.write_text(json.dumps({"run": "R-001", "status": "open"}))  # a stash pop
        with self.assertRaises(SystemExit):
            run.load_dispatch(self.problem, "R-001")

    def test_uncommitted_dispatch_is_still_readable(self):
        p = self.problem / "runs" / "R-001" / "dispatch.json"
        self.commit_all("empty")
        p.write_text(json.dumps({"run": "R-001", "status": "open"}))
        self.assertEqual(run.load_dispatch(self.problem, "R-001")["status"], "open")

    def test_truncated_ledger_still_shows_verified(self):
        new = {"event": "new", "id": "C-001", "ts": "2026-09-01T00:00:00Z",
               "actor": "a", "status": "proposed", "statement": "x",
               "conditions": [], "rests_on": [], "hash": "h"}
        up = {"event": "set", "id": "C-001", "ts": "2026-09-02T00:00:00Z",
              "actor": "b", "to": "verified", "hash": "h"}
        ledger = self.problem / "claims" / "ledger.jsonl"
        ledger.write_text(json.dumps(new) + "\n" + json.dumps(up) + "\n")
        self.commit_all("C-001 verified")
        ledger.write_text(json.dumps(new) + "\n")                      # rolled back
        known, order = claims.load(self.problem)
        self.assertEqual(known["C-001"]["status"], "verified")
        ledger.unlink()                                               # even deleted
        claims.forget_committed()
        known, order = claims.load(self.problem)
        self.assertEqual(known["C-001"]["status"], "verified")

    def test_own_append_is_visible_before_it_is_committed(self):
        # Between append and commit a regenerated view must already show
        # the new event; reading HEAD there made every view lag one event.
        new = {"event": "new", "id": "C-001", "ts": "2026-09-01T00:00:00Z",
               "actor": "a", "status": "proposed", "statement": "x",
               "conditions": [], "rests_on": [], "hash": "h"}
        self.commit_all("empty")
        claims.append(self.problem, new)
        known, order = claims.load(self.problem)
        self.assertEqual(order, ["C-001"])
        self.commit_all("C-001 new")
        known, order = claims.load(self.problem)
        self.assertEqual(order, ["C-001"])


if __name__ == "__main__":
    unittest.main()
