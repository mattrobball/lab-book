#!/usr/bin/env python3
"""Tests for claims.py. Each test builds a throwaway git repo in a temp dir.

Run from open-lab/scripts/tests/:  python3 -m unittest
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CLAIMS = Path(__file__).resolve().parent.parent / "claims.py"


ID_LINE = re.compile(r"^C-(?:[a-z0-9][a-z0-9-]*-)?\d+$")


def git(cwd, *args):
    return subprocess.run(["git"] + list(args), cwd=str(cwd), check=True,
                          capture_output=True, text=True)


def claim_id(out):
    """The allocated ID from `claims.py new`, which also prints one line
    saying what would settle the claim."""
    return next(l.strip() for l in out.splitlines() if ID_LINE.match(l.strip()))


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
        return claim_id(self.ok(*args).stdout)

    def ingest_run(self, run_id="R-007", verdict="PASS"):
        d = self.problem / "runs" / run_id / "packet"
        d.mkdir(parents=True)
        (d / "RETURN.json").write_text(json.dumps({"headline": "checked"}))
        if verdict:
            (d.parent / "ingest.json").write_text(json.dumps({"verdict": verdict}))
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
        self.assertIn("not one of the statuses", err)

    def test_verified_to_conditional_is_the_honest_correction(self):
        self.ingest_run()
        cid = self.new("A holds.")
        self.ok("set", cid, "verified", "--actor", "bob", "--evidence", "R-007",
                "--rests-on", "none")
        err = self.refused("set", cid, "conditional", "--actor", "bob",
                           "--conditions", "given the symmetry reduction")
        self.assertIn("--reason", err)
        err = self.refused("set", cid, "conditional", "--actor", "bob",
                           "--reason", "the reduction is not checked here")
        self.assertIn("--conditions", err)
        self.ok("set", cid, "conditional", "--actor", "bob",
                "--reason", "the reduction it uses is not checked here",
                "--conditions", "given the symmetry reduction")
        self.assertEqual(self.status_of(cid), "conditional")
        view = (self.problem / "claims" / (cid + ".md")).read_text()
        self.assertIn("given the symmetry reduction", view)
        self.assertIn("not checked here", view)          # the reason, in History

    def test_proposed_to_verified_checks_dependencies_too(self):
        """F-006: the rests-on check once ran only from conditional."""
        self.ingest_run("R-001")
        base = self.new("The bound is 224.", actor="alice")
        dep = self.new("Therefore the gap closes.", actor="carol")
        err = self.refused("set", dep, "verified", "--actor", "bob",
                           "--evidence", "R-001", "--rests-on", base)
        self.assertIn("rests on %s (proposed)" % base, err)
        self.assertEqual(self.status_of(dep), "proposed")

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

    def test_verified_rejects_a_refused_or_broken_run(self):
        """F-024: a refused packet still has its RETURN.json on disk, and a
        claim was once promoted on it. Only ingest.json is the record."""
        self.ingest_run("R-008", verdict=None)
        cid = self.new("A holds.")
        err = self.refused("set", cid, "verified", "--actor", "bob",
                           "--evidence", "R-008")
        self.assertIn("never ingested", err)
        self.ingest_run("R-009", verdict="UNINGESTABLE")
        err = self.refused("set", cid, "verified", "--actor", "bob",
                           "--evidence", "R-009")
        self.assertIn("UNINGESTABLE", err)

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
        self.ok("set", dep, "conditional", "--actor", "bob",
                "--conditions", "given %s" % base)
        err = self.refused("set", dep, "verified", "--actor", "bob",
                           "--evidence", "R-002")
        self.assertIn("rests on %s (proposed)" % base, err)
        # Verify the dependency, then the same promotion goes through.
        self.ok("set", base, "verified", "--actor", "bob", "--evidence", "R-001",
                "--rests-on", "none")
        self.ok("set", dep, "verified", "--actor", "bob", "--evidence", "R-002")
        self.assertEqual(self.status_of(dep), "verified")


class TestStatusAtBirth(LabCase):
    """A claim that only ever cites a source should not need two commands
    and two commits to say so."""

    def test_a_citation_is_recorded_with_the_statement(self):
        r = self.ok("new", "--statement", "The spectrum is known.",
                    "--actor", "director", "--status", "externally-established",
                    "--evidence", "Erdos 1962, Acta Math 7, p. 12")
        cid = claim_id(r.stdout)
        self.assertEqual(self.status_of(cid), "externally-established")
        self.assertIn("recorded on the evidence given", r.stdout)
        view = (self.problem / "claims" / (cid + ".md")).read_text()
        self.assertIn("**Status:** externally-established", view)
        self.assertIn("Erdos 1962", view)
        log = git(self.root, "log", "--pretty=%s").stdout
        self.assertIn("%s new (externally-established)" % cid, log)
        self.assertNotIn("proposed -> externally-established", log)

    def test_the_investigators_decision_likewise(self):
        cid = claim_id(self.ok("new", "--statement", "Take it as proved.",
                               "--actor", "director", "--status",
                               "accepted-by-investigator", "--evidence",
                               "Investigator instruction 2026-08-23: thesis "
                               "embargoed").stdout)
        self.assertEqual(self.status_of(cid), "accepted-by-investigator")

    def test_the_statuses_that_need_a_run_are_refused_at_birth(self):
        err = self.refused("new", "--statement", "A holds.", "--actor", "bob",
                           "--status", "verified", "--evidence", "R-007")
        self.assertIn("needs an ingested run", err)
        err = self.refused("new", "--statement", "A holds.", "--actor", "bob",
                           "--status", "externally-established")
        self.assertIn("citation", err)
        err = self.refused("new", "--statement", "A holds.", "--actor", "bob",
                           "--status", "externally-established",
                           "--evidence", "R-007")
        self.assertIn("not a citation", err)
        self.assertFalse((self.problem / "claims" / "ledger.jsonl").exists())

    def test_a_new_claim_says_what_would_settle_it(self):
        r = self.ok("new", "--statement", "A holds.", "--actor", "alice")
        self.assertIn("Dispatch a run that attacks it", r.stdout)
        self.assertIn("set %s verified" % claim_id(r.stdout), r.stdout)

    def test_without_an_investigator_the_actor_is_still_required(self):
        err = self.refused("new", "--statement", "A holds.")
        self.assertIn("--actor", err)
        self.assertIn("nobody has joined", err)


class TestAffirm(LabCase):
    """A room that looks at a claim, hears the objection and keeps the
    status has decided something."""

    def test_an_affirmation_is_on_the_ledger_and_in_the_history(self):
        cid = self.new("A holds.")
        err = self.refused("set", cid, "proposed", "--actor", "bob")
        self.assertIn("affirm %s" % cid, err)
        r = self.ok("affirm", cid, "--actor", "meeting 2026-08-27 (alice,bob)",
                    "--reason", "the objection was answered in the run")
        self.assertIn("affirmed as proposed", r.stdout)
        events = [json.loads(x) for x in
                  (self.problem / "claims" / "ledger.jsonl").read_text().splitlines()
                  if x.strip()]
        self.assertEqual(events[-1]["event"], "affirm")
        self.assertEqual(events[-1]["status"], "proposed")
        self.assertEqual(events[-1]["actor"], "meeting 2026-08-27 (alice,bob)")
        view = (self.problem / "claims" / (cid + ".md")).read_text()
        self.assertIn("affirmed as proposed", view)
        self.assertIn("the objection was answered", view)
        self.assertIn("%s affirmed (proposed)" % cid,
                      git(self.root, "log", "--pretty=%s").stdout)
        self.assertEqual(self.status_of(cid), "proposed")

    def test_an_unknown_claim_is_refused(self):
        err = self.refused("affirm", "C-404", "--actor", "bob")
        self.assertIn("not a claim in this ledger", err)


class TestProblemBySlug(LabCase):

    def test_a_bare_slug_names_the_problem(self):
        """Every listing and every agenda line spells a problem by its slug;
        a command copied from one should run."""
        r = self.ok("new", "--statement", "A holds.", "--actor", "alice",
                    "--problem", "demo", cwd=self.root)
        self.assertEqual(claim_id(r.stdout), "C-001")
        self.assertTrue((self.problem / "claims" / "ledger.jsonl").exists())
        err = self.refused("new", "--statement", "x", "--actor", "a",
                           "--problem", "no-such-problem", cwd=self.root)
        self.assertIn("no problem", err)


class TestCheck(LabCase):

    def test_check_flags_text_drift(self):
        self.ingest_run()
        cid = self.new("The check passed on all 40 inputs.")
        self.ok("set", cid, "verified", "--actor", "bob", "--evidence", "R-007",
                "--rests-on", "none")
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
        self.ok("set", cid, "verified", "--actor", "bob", "--evidence", "R-007",
                "--rests-on", "none")
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

        self.ok("set", cid, "conditional", "--actor", "director",
                "--conditions", "given the bound of the previous section")
        self.ok("set", cid, "verified", "--actor", "bob", "--evidence", "R-007",
                "--rests-on", "none")
        self.ok("set", cid, "proposed", "--actor", "director",
                "--reason", "the replay no longer runs on this machine")
        self.ok("set", cid, "verified", "--actor", "bob", "--evidence", "R-011",
                "--rests-on", "none")
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
