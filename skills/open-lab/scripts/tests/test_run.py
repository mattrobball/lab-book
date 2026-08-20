#!/usr/bin/env python3
"""Tests for run.py. Each test builds a throwaway git repo in a temp dir and
drives the script as a subprocess, the way a Director would.

Run from open-lab/scripts/tests/:  python3 -m unittest
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
RUN = SCRIPTS / "run.py"
CLAIMS = SCRIPTS / "claims.py"


def git(cwd, *args):
    return subprocess.run(["git"] + list(args), cwd=str(cwd), check=True,
                          capture_output=True, text=True)


class LabCase(unittest.TestCase):
    """A temp lab with one problem, a lab.json, and helpers for driving run.py."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="labruns-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Test Lab")
        git(self.root, "config", "user.email", "lab@example.invalid")
        (self.root / "lab.json").write_text(json.dumps({
            "roles": {"technician": {"model": "worker-a",
                                     "command": "/bin/echo {prompt}"},
                      "nameless": {"command": "/bin/echo {prompt}"}},
            "tools": ["python3"]}))
        self.problem = self.root / "problems" / "demo"
        (self.problem / "claims").mkdir(parents=True)
        (self.problem / "README.md").write_text("# demo\n")
        (self.problem / "STATUS.md").write_text("# Status: demo\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "seed")

    # -- driving the scripts ---------------------------------------------
    def script(self, path, *args, cwd=None):
        return subprocess.run([sys.executable, str(path)] + list(args),
                              cwd=str(cwd or self.problem), capture_output=True,
                              text=True)

    def run_py(self, *args, **kw):
        return self.script(RUN, *args, **kw)

    def ok(self, *args, **kw):
        r = self.run_py(*args, **kw)
        self.assertEqual(r.returncode, 0, "expected success, got:\n%s%s"
                         % (r.stdout, r.stderr))
        return r

    def refused(self, *args, **kw):
        r = self.run_py(*args, **kw)
        self.assertEqual(r.returncode, 2, "expected a refusal, got:\n%s%s"
                         % (r.stdout, r.stderr))
        self.assertTrue(r.stderr.startswith("Refused:"), r.stderr)
        return r.stderr

    def claims_py(self, *args, **kw):
        r = self.script(CLAIMS, *args, **kw)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout.strip().splitlines()[-1]

    # -- lab fixtures ----------------------------------------------------
    def brief(self, text="Count the caps.", name="b1.md"):
        d = self.problem / "briefs"
        d.mkdir(exist_ok=True)
        p = d / name
        p.write_text("# Brief: demo\n\n## Goal\n\n%s\n" % text)
        return p

    def dispatch(self, brief=None, extra=(), expect_warning=None):
        args = ["new", "--brief", str(brief or self.brief()), "--no-launch"]
        r = self.ok(*args, *extra)
        if expect_warning:
            self.assertIn(expect_warning, r.stdout)
        return r.stdout.split()[0], r

    def packet(self, rid, verdict="PASS", headline="The check ran clean.",
               drop=(), validation=None, ret=None, ret_text=None,
               marker="CHECK_OK", command=None):
        d = self.problem / "runs" / rid / "packet"
        d.mkdir(parents=True, exist_ok=True)
        if validation is None:
            validation = ("**Replay**\n\n    %s\n\nIt prints:\n\n    %s\n"
                          % (command or "printf '%s\\n' CHECK_OK", marker))
        body = [("What was done", "Ran the check on all three inputs."),
                ("Not claimed", "Nothing about n greater than 3."),
                ("Leads", "Dropped the greedy order; it plateaus at 8."),
                ("Validation", validation)]
        lines = ["# VERDICT: %s" % verdict, "", headline, ""]
        for name, text in body:
            if name in drop:
                continue
            lines += ["## %s" % name, "", text, ""]
        (d / "RESULT.md").write_text("\n".join(lines))
        if ret_text is None:
            base = {"headline": headline, "exits": ["checked"],
                    "validation": "replay", "machine_markers": [marker],
                    "honesty_tier": "machine-verified", "claims_used": [],
                    "claims_proposed": []}
            base.update(ret or {})
            ret_text = json.dumps(base)
        (d / "RETURN.json").write_text(ret_text)

    # -- readers ---------------------------------------------------------
    def ingest_json(self, rid):
        return json.loads((self.problem / "runs" / rid / "ingest.json").read_text())

    def dispatch_json(self, rid):
        return json.loads((self.problem / "runs" / rid / "dispatch.json").read_text())

    def ledger(self):
        p = self.problem / "claims" / "ledger.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] \
            if p.exists() else []

    def log(self):
        return git(self.root, "log", "--pretty=%s").stdout

    def entries(self):
        d = self.problem / "notebook" / "entries"
        return sorted(p.name for p in d.glob("N-*.md")) if d.is_dir() else []


class TestDispatch(LabCase):

    def test_refuses_without_a_model(self):
        err = self.refused("new", "--brief", str(self.brief()), "--no-launch",
                           "--role", "nameless")
        self.assertIn("names no model", err)
        self.assertFalse((self.problem / "runs").exists())

    def test_model_and_fence_are_recorded(self):
        rid, _ = self.dispatch(extra=["--allow", str(self.problem / "tools"),
                                      "--timeout", "42"])
        d = json.loads((self.problem / "runs" / rid / "dispatch.json").read_text())
        self.assertEqual(d["model"], "worker-a")
        self.assertEqual(d["timeout"], 42)
        self.assertEqual(d["status"], "open")
        self.assertIn("problems/demo/runs/%s" % rid, d["allowed"])
        self.assertIn("problems/demo/tools", d["allowed"])
        charter = (self.problem / "runs" / rid / "AGENTS.md").read_text()
        prompt = (self.problem / "runs" / rid / "PROMPT.md").read_text()
        for text in (charter, prompt):
            self.assertIn("Technician", text)
            self.assertIn("No `git` commands", text.replace("Run no", "No"))
            self.assertIn("Never invent a claim ID", text)
            self.assertIn("## Leads", text)
            self.assertIn("claims_proposed", text)
            self.assertIn("UNDECIDED", text)
        self.assertIn("Count the caps.", prompt)
        self.assertNotIn("Count the caps.", charter)

    def test_launching_captures_the_worker_output(self):
        """A worker that dies at its API exits quietly; the log is the only
        place that says so."""
        (self.root / "lab.json").write_text(json.dumps({"roles": {"technician": {
            "model": "worker-a",
            "command": 'sh -c "echo alive; echo dead >&2"'}}}))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "a noisy worker")
        r = self.ok("new", "--brief", str(self.brief()))
        rid = r.stdout.split()[0]
        self.assertIn("worker.log", r.stdout)
        log = self.problem / "runs" / rid / "worker.log"
        self.assertTrue(log.exists(), "no worker.log in %s" % rid)
        text = log.read_text()
        self.assertIn("alive", text)
        self.assertIn("dead", text)

    def test_a_silent_worker_is_named_as_such(self):
        (self.root / "lab.json").write_text(json.dumps({"roles": {"technician": {
            "model": "worker-a", "command": "/usr/bin/true"}}}))
        r = self.ok("new", "--brief", str(self.brief()))
        self.assertIn("printed nothing at all", r.stdout)
        rid = r.stdout.split()[0]
        self.assertEqual((self.problem / "runs" / rid / "worker.log").read_text(), "")

    def test_second_dispatch_of_the_same_brief_warns(self):
        b = self.brief()
        self.dispatch(b)
        self.dispatch(b, expect_warning="same brief")

    def test_claim_ids_in_the_brief_are_recorded(self):
        b = self.brief("Use C-001 [verified] — the bound is 9. Do not re-derive.")
        rid, _ = self.dispatch(b)
        d = json.loads((self.problem / "runs" / rid / "dispatch.json").read_text())
        self.assertEqual(d["claims_pasted"], ["C-001"])


class TestIngestGates(LabCase):

    def setUp(self):
        super().setUp()
        self.rid, _ = self.dispatch()

    def test_each_missing_section_refused(self):
        for name in ("What was done", "Not claimed", "Leads", "Validation"):
            self.packet(self.rid, drop=(name,))
            err = self.refused("ingest", self.rid)
            self.assertIn(name, err)
            self.assertIn("--record-broken", err)

    def test_bad_verdict_line_refused(self):
        self.packet(self.rid)
        p = self.problem / "runs" / self.rid / "packet" / "RESULT.md"
        p.write_text(p.read_text().replace("# VERDICT: PASS", "# Verdict: mostly"))
        err = self.refused("ingest", self.rid)
        self.assertIn("must be exactly", err)

    def test_invalid_json_refused(self):
        self.packet(self.rid, ret_text='{"headline": "oops",,}')
        err = self.refused("ingest", self.rid)
        self.assertIn("not valid JSON", err)

    def test_missing_field_refused(self):
        self.packet(self.rid, ret_text=json.dumps({"headline": "thin"}))
        err = self.refused("ingest", self.rid)
        self.assertIn("has no exits", err)

    def test_self_named_actor_refused(self):
        self.packet(self.rid, ret={"actor": "worker-a"})
        err = self.refused("ingest", self.rid)
        self.assertIn("never name themselves", err)

    def test_invented_claim_id_in_proposed_refused(self):
        self.packet(self.rid, ret={"claims_proposed": ["C-099 the bound is 224."]})
        err = self.refused("ingest", self.rid)
        self.assertIn("contains the claim ID C-099", err)
        self.assertEqual(self.ledger(), [])

    def test_claims_used_never_pasted_refused(self):
        self.packet(self.rid, ret={"claims_used": ["C-005"]})
        err = self.refused("ingest", self.rid)
        self.assertIn("never pasted into the brief", err)

    def test_fence_violation_refused(self):
        self.packet(self.rid)
        (self.problem / "rogue.txt").write_text("written where it should not be\n")
        err = self.refused("ingest", self.rid)
        self.assertIn("wrote outside its fence", err)
        self.assertIn("problems/demo/rogue.txt", err)
        self.assertFalse((self.problem / "runs" / self.rid / "ingest.json").exists())

    def test_replay_without_a_command_refused(self):
        self.packet(self.rid, validation="**Replay** — just trust the output.")
        err = self.refused("ingest", self.rid)
        self.assertIn("holds no command", err)

    def test_double_ingest_refused(self):
        self.packet(self.rid)
        self.ok("ingest", self.rid)
        err = self.refused("ingest", self.rid)
        self.assertIn("already ingested", err)
        self.assertEqual(len(self.entries()), 1)

    def test_record_broken_files_it_then_ingest_refuses(self):
        self.packet(self.rid, ret_text="{ not json at all")
        self.refused("ingest", self.rid)
        r = self.ok("ingest", self.rid, "--record-broken")
        self.assertIn("UNINGESTABLE", r.stdout)
        self.assertEqual(self.ingest_json(self.rid)["verdict"], "UNINGESTABLE")
        self.assertEqual(self.ingest_json(self.rid)["claims"], [])
        self.assertIn("UNINGESTABLE", self.log())
        self.assertEqual(len(self.entries()), 1)
        err = self.refused("ingest", self.rid)
        self.assertIn("already ingested", err)

    def test_unknown_run_refused(self):
        err = self.refused("ingest", "R-404")
        self.assertIn("no run R-404", err)


class TestHonestyTier(LabCase):

    def test_marker_absent_is_asserted(self):
        rid, _ = self.dispatch()
        self.packet(rid, marker="NEVER_PRINTED_OK",
                    command="printf '%s\\n' SOMETHING_ELSE")
        r = self.ok("ingest", rid)
        self.assertIn("asserted", r.stdout)
        self.assertIn("never printed", r.stdout)
        self.assertEqual(self.ingest_json(rid)["honesty_tier"], "asserted")

    def test_nonzero_exit_is_asserted_even_with_markers(self):
        rid, _ = self.dispatch()
        self.packet(rid, command="printf '%s\\n' CHECK_OK; exit 3")
        r = self.ok("ingest", rid)
        self.assertIn("exited 3", r.stdout)
        self.assertEqual(self.ingest_json(rid)["honesty_tier"], "asserted")

    def test_clean_replay_is_machine_verified(self):
        rid, _ = self.dispatch()
        self.packet(rid)
        r = self.ok("ingest", rid)
        self.assertIn("machine-verified", r.stdout)
        rec = self.ingest_json(rid)
        self.assertEqual(rec["honesty_tier"], "machine-verified")
        self.assertEqual(rec["replay"]["exit"], 0)
        self.assertEqual(rec["warnings"], [])

    def test_worker_tier_is_not_believed(self):
        rid, _ = self.dispatch()
        self.packet(rid, marker="NEVER_PRINTED_OK",
                    command="printf '%s\\n' SOMETHING_ELSE",
                    ret={"honesty_tier": "machine-verified"})
        r = self.ok("ingest", rid)
        self.assertIn("the worker reported machine-verified", r.stdout)
        self.assertEqual(self.ingest_json(rid)["honesty_tier"], "asserted")

    def test_review_is_asserted_until_a_referee_run_checks_it(self):
        first, _ = self.dispatch(self.brief("Prove the bound.", "b1.md"))
        self.packet(first, validation="**Review** — a referee must recheck the "
                                      "induction step for n = 4.",
                    ret={"validation": "review", "machine_markers": []})
        r = self.ok("ingest", first)
        self.assertIn("asserted", r.stdout)
        self.assertIn("no referee run has checked this yet", r.stdout)
        self.assertIn("%s declared a review" % first, self.ok("check").stdout)

        second, _ = self.dispatch(self.brief("Referee %s." % first, "b2.md"),
                                  extra=["--model", "worker-b"])
        self.packet(second, headline="The induction step holds.",
                    ret={"reviewed": [first]})
        self.ok("ingest", second)
        self.assertEqual(self.ingest_json(first)["honesty_tier"], "hand-checked")
        self.assertEqual(self.ingest_json(first)["reviewed_by"], [second])
        self.assertEqual(self.dispatch_json(first)["honesty_tier"], "hand-checked")
        self.assertNotIn("declared a review", self.ok("check").stdout)

    def test_a_review_never_overwrites_machine_verified(self):
        """A replay this lab ran outranks a referee reading the work: the
        review is recorded, the tier it earned is left alone."""
        first, _ = self.dispatch(self.brief("Count them.", "b1.md"))
        self.packet(first)
        self.ok("ingest", first)
        self.assertEqual(self.ingest_json(first)["honesty_tier"], "machine-verified")

        second, _ = self.dispatch(self.brief("Referee %s." % first, "b2.md"),
                                  extra=["--model", "worker-b"])
        self.packet(second, headline="The count holds.", ret={"reviewed": [first]})
        r = self.ok("ingest", second)
        self.assertIn("stays machine-verified", r.stdout)
        self.assertIn("never overwrites a tier a replay earned", r.stdout)
        rec = self.ingest_json(first)
        self.assertEqual(rec["honesty_tier"], "machine-verified")
        self.assertEqual(rec["reviewed_by"], [second])
        self.assertEqual(self.dispatch_json(first)["honesty_tier"], "machine-verified")

    def test_a_referee_with_the_same_actor_is_refused(self):
        first, _ = self.dispatch(self.brief("Prove the bound.", "b1.md"))
        self.packet(first, validation="**Review** — recheck the induction step.",
                    ret={"validation": "review", "machine_markers": []})
        self.ok("ingest", first)
        second, _ = self.dispatch(self.brief("Referee it.", "b2.md"))
        self.packet(second, ret={"reviewed": [first]})
        err = self.refused("ingest", second)
        self.assertIn("A review by the same actor validates nothing", err)


class TestSpine(LabCase):

    def test_offline_loop_from_brief_to_catchup(self):
        # A claim already on file, which the brief pastes for the worker.
        base = self.claims_py("new", "--statement",
                              "Every cap in AG(3,3) has at most 9 points.",
                              "--actor", "director")
        brief = self.brief("Recount the caps for n = 3.\n\n## Context carried\n\n"
                           "%s [proposed] — every cap in AG(3,3) has at most 9 "
                           "points. Do not re-derive.\n" % base)
        rid, _ = self.dispatch(brief)
        self.assertEqual(rid, "R-001")

        self.packet(rid, headline="Recounted: the largest cap in AG(3,3) is 9.",
                    ret={"claims_used": [base],
                         "claims_proposed": ["The largest cap in AG(4,3) has 20 "
                                             "points."]})
        r = self.ok("ingest", rid)
        self.assertIn("R-001 PASS (machine-verified)", r.stdout)

        # The proposed claim went through the ledger, as proposed, credited to
        # the actor dispatch stamped — never to the worker's own say-so.
        rec = [x for x in self.ledger() if x["event"] == "new"][-1]
        self.assertEqual(rec["status"], "proposed")
        self.assertEqual(rec["actor"], "worker-a")
        self.assertEqual(rec["id"], "C-002")
        self.assertEqual(self.ingest_json(rid)["claims"], ["C-002"])
        self.assertIn("C-002", (self.problem / "CLAIMS.md").read_text())

        # Notebook entry and index.
        self.assertEqual(len(self.entries()), 1)
        entry = (self.problem / "notebook" / "entries" / self.entries()[0]).read_text()
        self.assertIn("**Verdict:** PASS", entry)
        self.assertIn("machine-verified", entry)
        self.assertIn("CHECK_OK", entry)
        self.assertIn("Dropped the greedy order", entry)      # Leads, verbatim
        self.assertIn("C-002", entry)
        index = (self.problem / "notebook" / "INDEX.md").read_text()
        self.assertIn(self.entries()[0][:-3], index)
        self.assertIn("PASS", index)

        # The commit carries the verdict, and nothing is left uncommitted.
        self.assertIn("R-001 ingested: PASS", self.log())
        self.assertEqual(git(self.root, "status", "--porcelain").stdout.strip(), "")

        cat = self.ok("catchup", "2020-01-01").stdout
        self.assertIn("R-001 PASS (machine-verified)", cat)
        self.assertIn("C-002 stated as proposed", cat)
        self.assertIn("Still open:\n  nothing", cat)
        self.assertIn("run(s) ingested since", cat)

        note = self.ok("note", "--headline", "Dropping the greedy order",
                       "--body", "It plateaus at 8, so the next run tries the "
                                 "lexicographic sweep instead.",
                       "--actor", "director")
        self.assertIn("Entry:", note.stdout)
        self.assertEqual(len(self.entries()), 2)
        self.assertIn("note: Dropping the greedy order", self.log())
        self.assertIn("**Actor:** director",
                      (self.problem / "notebook" / "entries" /
                       self.entries()[1]).read_text())
        self.assertIn(self.entries()[1][:-3],
                      (self.problem / "notebook" / "INDEX.md").read_text())

    def test_near_duplicate_claim_warns(self):
        self.claims_py("new", "--statement",
                       "The largest cap in AG(4,3) has 20 points.",
                       "--actor", "director")
        rid, _ = self.dispatch()
        self.packet(rid, ret={"claims_proposed":
                              ["The largest cap in AG(4,3) has 20 points."]})
        r = self.ok("ingest", rid)
        self.assertIn("looks close to C-001", r.stdout)
        self.assertIn("C-002", r.stdout)

    def test_check_flags_an_open_run(self):
        rid, _ = self.dispatch()
        self.assertIn("%s is still open" % rid, self.ok("check").stdout)
        self.packet(rid)
        self.ok("ingest", rid)
        self.assertIn("Nothing to flag", self.ok("check").stdout)

    def test_refuses_outside_a_git_repo(self):
        loose = Path(tempfile.mkdtemp(prefix="nogit-"))
        self.addCleanup(shutil.rmtree, loose, ignore_errors=True)
        (loose / "runs").mkdir()
        (loose / "b.md").write_text("# Brief\n")
        err = self.refused("new", "--brief", str(loose / "b.md"), "--model", "m",
                           "--no-launch", cwd=loose)
        self.assertIn("git", err)


if __name__ == "__main__":
    unittest.main()
