#!/usr/bin/env python3
"""Tests for claims.py. Each test builds a throwaway git repo in a temp dir.

Run from open-lab/scripts/tests/:  python3 -m unittest
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CLAIMS = Path(__file__).resolve().parent.parent / "claims.py"


def git(cwd, *args):
    return subprocess.run(["git"] + list(args), cwd=str(cwd), check=True,
                          capture_output=True, text=True)


class LabCase(unittest.TestCase):
    """A temp repo with one problem, plus helpers for driving claims.py."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="labclaims-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Test Lab")
        git(self.root, "config", "user.email", "lab@example.invalid")
        self.problem = self.root / "problems" / "demo"
        (self.problem / "claims").mkdir(parents=True)
        (self.problem / "README.md").write_text("# demo\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "seed")

    # -- helpers ---------------------------------------------------------
    def claims(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(CLAIMS)] + list(args),
                              cwd=str(cwd or self.problem), capture_output=True,
                              text=True)

    def ok(self, *args, **kw):
        r = self.claims(*args, **kw)
        self.assertEqual(r.returncode, 0, "expected success, got:\n%s%s"
                         % (r.stdout, r.stderr))
        return r

    def refused(self, *args, **kw):
        r = self.claims(*args, **kw)
        self.assertEqual(r.returncode, 2, "expected a refusal, got:\n%s%s"
                         % (r.stdout, r.stderr))
        self.assertTrue(r.stderr.startswith("Refused:"), r.stderr)
        return r.stderr

    def new(self, statement, actor="alice", **kw):
        args = ["new", "--statement", statement, "--actor", actor]
        for k, v in kw.items():
            args += ["--" + k.replace("_", "-"), v]
        return self.ok(*args).stdout.strip().splitlines()[-1]

    def ingest_run(self, run_id="R-007"):
        d = self.problem / "runs" / run_id / "packet"
        d.mkdir(parents=True)
        (d / "RETURN.json").write_text(json.dumps({"headline": "checked"}))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "run %s" % run_id)

    def commits(self):
        return int(git(self.root, "rev-list", "--count", "HEAD").stdout.strip())

    def status_of(self, cid):
        line = [json.loads(x) for x in
                (self.problem / "claims" / "ledger.jsonl").read_text().splitlines() if x.strip()]
        last = [r for r in line if r["id"] == cid][-1]
        return last.get("to", last.get("status"))


class TestAllocation(LabCase):

    def test_contention_never_reuses_an_id(self):
        """Another allocator holding the next marker pushes us past it."""
        first = self.new("Method A terminates on every input.")
        self.assertEqual(first, "C-001")
        # Simulate a racing allocator that won the O_EXCL create for C-002.
        marker = self.problem / "claims" / "_ids" / "C-002"
        os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        second = self.new("Method B terminates on every input.")
        self.assertEqual(second, "C-003")
        ids = sorted(p.name for p in (self.problem / "claims" / "_ids").iterdir())
        self.assertEqual(ids, ["C-001", "C-002", "C-003"])
        self.assertEqual(len(ids), len(set(ids)))

    def test_refuses_outside_a_git_repo(self):
        loose = Path(tempfile.mkdtemp(prefix="nogit-"))
        self.addCleanup(shutil.rmtree, loose, ignore_errors=True)
        (loose / "claims").mkdir()
        err = self.refused("new", "--statement", "x", "--actor", "alice", cwd=loose)
        self.assertIn("git", err)


class TestTransitions(LabCase):

    def test_nonsense_status_refused(self):
        cid = self.new("A holds.")
        err = self.refused("set", cid, "probably-true", "--actor", "bob")
        self.assertIn("not one of the six statuses", err)

    def test_verified_to_conditional_refused(self):
        self.ingest_run()
        cid = self.new("A holds.")
        self.ok("set", cid, "verified", "--actor", "bob", "--evidence", "R-007")
        err = self.refused("set", cid, "conditional", "--actor", "bob")
        self.assertIn("cannot become conditional", err)
        self.assertEqual(self.status_of(cid), "verified")

    def test_off_refuted_refused(self):
        cid = self.new("A holds.")
        self.ok("set", cid, "refuted", "--actor", "bob")
        err = self.refused("set", cid, "proposed", "--actor", "bob")
        self.assertIn("state it as a new claim", err)

    def test_off_superseded_refused(self):
        old = self.new("A holds sometimes.")
        new = self.new("A holds always.")
        self.ok("set", old, "superseded", "--actor", "bob", "--by", new)
        err = self.refused("set", old, "verified", "--actor", "bob",
                           "--evidence", "R-007")
        self.assertIn("that is final", err)

    def test_supersede_needs_a_replacement(self):
        cid = self.new("A holds.")
        err = self.refused("set", cid, "superseded", "--actor", "bob")
        self.assertIn("--by", err)
        err = self.refused("set", cid, "superseded", "--actor", "bob", "--by", "C-099")
        self.assertIn("not a claim in this ledger", err)


class TestPromotionGates(LabCase):

    def test_self_verification_refused(self):
        self.ingest_run()
        cid = self.new("A holds.", actor="alice")
        err = self.refused("set", cid, "verified", "--actor", "alice",
                           "--evidence", "R-007")
        self.assertIn("never confirms it", err)
        self.assertEqual(self.status_of(cid), "proposed")

    def test_verified_needs_evidence(self):
        cid = self.new("A holds.")
        err = self.refused("set", cid, "verified", "--actor", "bob")
        self.assertIn("--evidence naming an ingested run", err)

    def test_verified_rejects_a_citation(self):
        cid = self.new("A holds.")
        err = self.refused("set", cid, "verified", "--actor", "bob",
                           "--evidence", "Erdos 1962, Acta Math 7, p. 12")
        self.assertIn("externally-established, not", err)

    def test_verified_rejects_a_run_not_on_record(self):
        cid = self.new("A holds.")
        err = self.refused("set", cid, "verified", "--actor", "bob",
                           "--evidence", "R-042")
        self.assertIn("no ingested run R-042", err)

    def test_externally_established_needs_a_citation(self):
        self.ingest_run()
        cid = self.new("A holds.")
        err = self.refused("set", cid, "externally-established", "--actor", "bob")
        self.assertIn("citation", err)
        err = self.refused("set", cid, "externally-established", "--actor", "bob",
                           "--evidence", "R-007")
        self.assertIn("not a citation", err)
        self.ok("set", cid, "externally-established", "--actor", "bob",
                "--evidence", "Erdos 1962, Acta Math 7, p. 12")
        self.assertEqual(self.status_of(cid), "externally-established")

    def test_conditional_needs_its_dependency_verified(self):
        self.ingest_run("R-001")
        self.ingest_run("R-002")
        base = self.new("The bound is 224.", actor="alice")
        dep = self.new("Therefore the gap closes.", actor="carol", rests_on=base)
        self.ok("set", dep, "conditional", "--actor", "bob")
        err = self.refused("set", dep, "verified", "--actor", "bob",
                           "--evidence", "R-002")
        self.assertIn("rests on %s (proposed)" % base, err)
        # Verify the dependency, then the same promotion goes through.
        self.ok("set", base, "verified", "--actor", "bob", "--evidence", "R-001")
        self.ok("set", dep, "verified", "--actor", "bob", "--evidence", "R-002")
        self.assertEqual(self.status_of(dep), "verified")


class TestCheck(LabCase):

    def test_check_flags_text_drift(self):
        self.ingest_run()
        cid = self.new("The check passed on all 40 inputs.")
        self.ok("set", cid, "verified", "--actor", "bob", "--evidence", "R-007")
        view = self.problem / "claims" / (cid + ".md")
        view.write_text(view.read_text().replace("all 40 inputs", "every input"))
        r = self.ok("check")
        self.assertIn("no longer says what it said", r.stdout)
        self.assertEqual(r.returncode, 0)

    def test_check_flags_dangling_rests_on_and_stays_advisory(self):
        cid = self.new("A holds.", rests_on="C-404")
        r = self.ok("check")
        self.assertIn("C-404", r.stdout)
        self.assertIn(cid, r.stdout)

    def test_check_is_quiet_when_all_is_well(self):
        self.ingest_run()
        cid = self.new("A holds.")
        self.ok("set", cid, "verified", "--actor", "bob", "--evidence", "R-007")
        r = self.ok("check")
        self.assertIn("Nothing to flag", r.stdout)


class TestSpine(LabCase):

    def test_full_life_of_a_claim(self):
        self.ingest_run("R-007")
        self.ingest_run("R-011")
        before = self.commits()

        cid = self.new("Every cap in AG(3,3) has at most 9 points.", actor="alice")
        self.assertEqual(cid, "C-001")
        self.assertEqual(self.commits(), before + 1)

        self.ok("set", cid, "conditional", "--actor", "director")
        self.ok("set", cid, "verified", "--actor", "bob", "--evidence", "R-007")
        self.ok("set", cid, "proposed", "--actor", "director")
        self.ok("set", cid, "verified", "--actor", "bob", "--evidence", "R-011")
        self.assertEqual(self.status_of(cid), "verified")
        # one commit for the allocation and one for each of the four moves
        self.assertEqual(self.commits(), before + 5)

        sharper = self.new("Every cap in AG(3,3) has exactly 9 points.", actor="carol")
        self.ok("set", cid, "superseded", "--actor", "director", "--by", sharper)
        self.assertEqual(self.status_of(cid), "superseded")

        view = (self.problem / "claims" / (cid + ".md")).read_text()
        self.assertIn("**Status:** superseded", view)
        self.assertIn("**Superseded by:** %s" % sharper, view)
        self.assertIn("**Discovered by:** alice", view)
        self.assertIn("R-011", view)
        self.assertIn("proposed -> verified", view)

        index = (self.problem / "CLAIMS.md").read_text()
        self.assertIn("[%s](claims/%s.md)" % (cid, cid), index)
        self.assertIn("[%s](claims/%s.md)" % (sharper, sharper), index)
        self.assertIn("superseded", index)

        log = git(self.root, "log", "--pretty=%s").stdout
        self.assertIn("C-001 new (proposed)", log)
        self.assertIn("C-001 proposed -> verified (R-011)", log)
        self.assertIn("C-001 verified -> superseded (by C-002)", log)
        # nothing left uncommitted
        self.assertEqual(git(self.root, "status", "--porcelain").stdout.strip(), "")

    def test_supersession_chains(self):
        a = self.new("First cut.")
        b = self.new("Second cut.")
        c = self.new("Third cut.")
        self.ok("set", a, "superseded", "--actor", "director", "--by", b)
        self.ok("set", b, "superseded", "--actor", "director", "--by", c)
        self.assertEqual(self.status_of(a), "superseded")
        self.assertEqual(self.status_of(b), "superseded")
        self.assertIn("Nothing to flag", self.ok("check").stdout)


if __name__ == "__main__":
    unittest.main()
