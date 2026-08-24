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
        self.assertIn("replayed: no", r.stdout)
        self.assertIn("never printed", r.stdout)
        self.assertIs(self.ingest_json(rid)["replayed"], False)

    def test_nonzero_exit_is_asserted_even_with_markers(self):
        rid, _ = self.dispatch()
        self.packet(rid, command="printf '%s\\n' CHECK_OK; exit 3")
        r = self.ok("ingest", rid)
        self.assertIn("exited 3", r.stdout)
        self.assertIs(self.ingest_json(rid)["replayed"], False)

    def test_clean_replay_is_recorded(self):
        rid, _ = self.dispatch()
        self.packet(rid)
        r = self.ok("ingest", rid)
        self.assertIn("replayed: yes", r.stdout)
        rec = self.ingest_json(rid)
        self.assertIs(rec["replayed"], True)
        self.assertEqual(rec["replay"]["exit"], 0)
        self.assertEqual(rec["warnings"], [])

    def test_worker_self_grade_is_ignored(self):
        """Whatever a worker says about its own standing is not read at all:
        replayed is computed here, from the replay alone."""
        rid, _ = self.dispatch()
        self.packet(rid, marker="NEVER_PRINTED_OK",
                    command="printf '%s\\n' SOMETHING_ELSE",
                    ret={"honesty_tier": "machine-verified"})
        r = self.ok("ingest", rid)
        self.assertIs(self.ingest_json(rid)["replayed"], False)
        self.assertNotIn("machine-verified", r.stdout)

    def test_review_is_asserted_until_a_referee_run_checks_it(self):
        first, _ = self.dispatch(self.brief("Prove the bound.", "b1.md"))
        self.packet(first, validation="**Review** — a referee must recheck the "
                                      "induction step for n = 4.",
                    ret={"validation": "review", "machine_markers": []})
        r = self.ok("ingest", first)
        self.assertIn("replayed: no", r.stdout)
        self.assertIn("no referee run has checked", r.stdout)
        self.assertIn("owe a review", self.ok("catchup", "2020-01-01").stdout)

        second, _ = self.dispatch(self.brief("Referee %s." % first, "b2.md"),
                                  extra=["--model", "worker-b"])
        self.packet(second, headline="The induction step holds.",
                    ret={"reviewed": [first]})
        self.ok("ingest", second)
        self.assertEqual(self.ingest_json(first)["reviewed_by"], [second])
        self.assertNotIn("owe a review", self.ok("catchup", "2020-01-01").stdout)

    def test_replay_and_review_are_separate_facts(self):
        """Not a ladder: a replayed run that also gets reviewed records both,
        and neither rewrites the other."""
        first, _ = self.dispatch(self.brief("Count them.", "b1.md"))
        self.packet(first)
        self.ok("ingest", first)
        self.assertIs(self.ingest_json(first)["replayed"], True)

        second, _ = self.dispatch(self.brief("Referee %s." % first, "b2.md"),
                                  extra=["--model", "worker-b"])
        self.packet(second, headline="The count holds.", ret={"reviewed": [first]})
        r = self.ok("ingest", second)
        self.assertIn("reviewed by %s" % second, r.stdout)
        rec = self.ingest_json(first)
        self.assertIs(rec["replayed"], True)
        self.assertEqual(rec["reviewed_by"], [second])

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
        self.assertIn("R-001 PASS (replayed: yes)", r.stdout)

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
        self.assertIn("**Replayed:** yes", entry)
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
        self.assertIn("R-001 PASS (replayed)", cat)
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

    def test_open_runs_listed_by_catchup(self):
        rid, _ = self.dispatch()
        self.assertIn(rid, self.ok("catchup", "2020-01-01").stdout)
        self.packet(rid)
        self.ok("ingest", rid)
        self.assertIn("Still open:\n  nothing",
                      self.ok("catchup", "2020-01-01").stdout)

    def test_refuses_outside_a_git_repo(self):
        loose = Path(tempfile.mkdtemp(prefix="nogit-"))
        self.addCleanup(shutil.rmtree, loose, ignore_errors=True)
        (loose / "runs").mkdir()
        (loose / "b.md").write_text("# Brief\n")
        err = self.refused("new", "--brief", str(loose / "b.md"), "--model", "m",
                           "--no-launch", cwd=loose)
        self.assertIn("git", err)


class TestParallelFence(LabCase):
    """The fence judges what this worker could have written, never what the
    Director or a sibling run did while it worked."""

    def test_director_commits_do_not_implicate_a_worker(self):
        rid, _ = self.dispatch()
        self.packet(rid)
        # The Director rewrites belief documents mid-flight, any subject line.
        (self.problem / "STATUS.md").write_text("# Status: demo\n\nRewritten.\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m",
            "Reduce remaining classification to three proof gates")
        self.ok("ingest", rid)
        self.assertEqual(self.dispatch_json(rid)["status"], "ingested")

    def test_sibling_run_dirt_does_not_implicate_a_worker(self):
        rid, _ = self.dispatch()
        self.packet(rid)
        sibling = self.problem / "runs" / "R-099" / "packet"
        sibling.mkdir(parents=True)
        (sibling / "scratch.py").write_text("pass\n")     # uncommitted
        self.ok("ingest", rid)
        self.assertEqual(self.dispatch_json(rid)["status"], "ingested")

    def test_a_real_escape_is_still_caught_and_the_reason_kept(self):
        rid, _ = self.dispatch()
        self.packet(rid)
        (self.problem / "stray.txt").write_text("worker was here\n")
        err = self.refused("ingest", rid)
        self.assertIn("wrote outside its fence", err)
        self.assertIn("stray.txt", err)
        refusal = self.problem / "runs" / rid / "refusal.txt"
        self.assertTrue(refusal.exists())
        self.assertIn("stray.txt", refusal.read_text())


class TestFailureTaxonomy(LabCase):

    def test_record_broken_quotes_the_refusal_and_salvages_leads(self):
        rid, _ = self.dispatch()
        self.packet(rid, drop=("Not claimed",),
                    ret={"claims_proposed": ["The bound is 17."]})
        self.refused("ingest", rid)                       # writes refusal.txt
        r = self.ok("ingest", rid, "--record-broken")
        self.assertIn("UNINGESTABLE", r.stdout)
        rec = self.ingest_json(rid)
        self.assertIn("Not claimed", rec["refused_for"][0])
        entry = (self.problem / "notebook" / "entries" /
                 self.entries()[0]).read_text()
        self.assertIn("Not claimed", entry)               # the reason, named
        self.assertIn("The bound is 17.", entry)          # salvage, untrusted
        self.assertIn("Dropped the greedy order", entry)  # leads survive
        self.assertIn("not on record", entry)
        self.assertEqual(rec["claims"], [])

    def test_no_packet_files_as_harness_failure(self):
        rid, _ = self.dispatch()
        r = self.ok("ingest", rid, "--record-broken")
        self.assertIn("HARNESS-FAILURE", r.stdout)
        self.assertEqual(self.ingest_json(rid)["verdict"], "HARNESS-FAILURE")
        self.assertIn("HARNESS-FAILURE", self.log())

    def test_pending_verdict_names_the_unfinished_worker(self):
        rid, _ = self.dispatch()
        self.packet(rid, verdict="PENDING")
        err = self.refused("ingest", rid)
        self.assertIn("PENDING", err)
        self.assertIn("never finished", err)


class TestVoidLintWaive(LabCase):

    def test_void_closes_a_run_that_produced_nothing(self):
        rid, _ = self.dispatch()
        r = self.ok("void", rid, "--reason", "launch blocked; superseded by a "
                                             "fresh dispatch")
        self.assertIn("voided", r.stdout)
        self.assertEqual(self.dispatch_json(rid)["status"], "void")
        self.assertIn("VOID", self.log())
        self.assertNotIn(rid, self.ok("catchup", "2020-01-01")
                         .stdout.split("Still open:")[1])

    def test_void_refuses_when_a_packet_exists(self):
        rid, _ = self.dispatch()
        self.packet(rid)
        err = self.refused("void", rid, "--reason", "tidy")
        self.assertIn("has a packet", err)

    def test_lint_reports_and_passes(self):
        rid, _ = self.dispatch()
        self.packet(rid, drop=("Leads",))
        r = self.ok("lint", rid)
        self.assertIn("does not pass", r.stdout)
        self.packet(rid)
        self.assertIn("passes the contract", self.ok("lint", rid).stdout)
        # lint changed nothing: the run is still open and ingestable
        self.assertEqual(self.dispatch_json(rid)["status"], "open")

    def test_waive_review_clears_the_owed_line(self):
        rid, _ = self.dispatch()
        self.packet(rid, validation="**Review** — recheck step 3.",
                    ret={"validation": "review", "machine_markers": []})
        self.ok("ingest", rid)
        self.assertIn("owe a review", self.ok("catchup", "2020-01-01").stdout)
        self.ok("waive-review", rid, "--reason", "referee providers are down; "
                                                 "accepted as-is for now")
        self.assertNotIn("owe a review", self.ok("catchup", "2020-01-01").stdout)


class TestIndependence(LabCase):
    """Promotion records how independent the check was; same model needs an
    explicit flag and is marked, never refused outright."""

    def promote(self, *extra):
        first, _ = self.dispatch(self.brief("Find the bound.", "b1.md"))
        self.packet(first, ret={"claims_proposed": ["The bound is 9."]})
        self.ok("ingest", first)
        cid = self.ingest_json(first)["claims"][0]
        second, _ = self.dispatch(self.brief("C claims the bound is 9; review "
                                             "the claim adversarially but "
                                             "fairly.", "b2.md"), extra=extra)
        self.packet(second, headline="Attacked it; could not break it.")
        self.ok("ingest", second)
        return cid, second

    def test_same_model_needs_the_flag_and_is_marked(self):
        cid, ev = self.promote()                          # both worker-a
        err = self.claims_refused("set", cid, "verified", "--actor", "director",
                                  "--evidence", ev, "--rests-on", "none")
        self.assertIn("same model", err)
        self.claims_ok("set", cid, "verified", "--actor", "director",
                       "--evidence", ev, "--rests-on", "none",
                       "--accept-same-model")
        view = (self.problem / "claims" / (cid + ".md")).read_text()
        self.assertIn("**Independence:** none (same model", view)

    def test_cross_model_promotes_clean_and_is_marked_full(self):
        cid, ev = self.promote("--model", "worker-b")
        self.claims_ok("set", cid, "verified", "--actor", "director",
                       "--evidence", ev, "--rests-on", "none")
        view = (self.problem / "claims" / (cid + ".md")).read_text()
        self.assertIn("**Independence:** full", view)

    def test_a_fall_prints_its_dependents(self):
        cid, ev = self.promote("--model", "worker-b")
        self.claims_ok("set", cid, "verified", "--actor", "director",
                       "--evidence", ev, "--rests-on", "none")
        dep = self.claims_py("new", "--statement", "Therefore the gap closes.",
                             "--actor", "director", "--rests-on", cid)
        r = self.claims_ok("set", cid, "refuted", "--actor", "director")
        self.assertIn("Standing on %s" % cid, r.stdout)
        self.assertIn(dep, r.stdout)

    def claims_ok(self, *args):
        r = self.script(CLAIMS, *args)
        self.assertEqual(r.returncode, 0, "expected success, got:\n%s%s"
                         % (r.stdout, r.stderr))
        return r

    def claims_refused(self, *args):
        r = self.script(CLAIMS, *args)
        self.assertEqual(r.returncode, 2, "expected refusal, got:\n%s%s"
                         % (r.stdout, r.stderr))
        return r.stderr


class TestAcceptedByInvestigator(LabCase):

    def test_records_the_decision_and_catchup_lists_it(self):
        cid = self.claims_py("new", "--statement",
                             "Steen: the type-D spectrum is {0,...,n-2}.",
                             "--actor", "director")
        err = self.script(CLAIMS, "set", cid, "accepted-by-investigator",
                          "--actor", "director").stderr
        self.assertIn("--evidence", err)
        r = self.script(CLAIMS, "set", cid, "accepted-by-investigator",
                        "--actor", "director", "--evidence",
                        "Investigator instruction 2026-08-23: take it as "
                        "proved; thesis embargoed to 2099")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("accepted on the Investigator's word",
                      self.ok("catchup", "2020-01-01").stdout)


class TestDuplicateWarningLifecycle(LabCase):

    def test_warning_persists_until_the_claim_moves(self):
        self.claims_py("new", "--statement",
                       "The largest cap in AG(4,3) has 20 points.",
                       "--actor", "director")
        rid, _ = self.dispatch()
        self.packet(rid, ret={"claims_proposed":
                              ["The largest cap in AG(4,3) has 20 points."]})
        self.ok("ingest", rid)
        cid = self.ingest_json(rid)["claims"][0]
        self.assertIn("duplicate warning", self.ok("catchup", "2020-01-01").stdout)
        self.claims_py("set", cid, "superseded", "--actor", "director",
                       "--by", "C-001")
        self.assertNotIn("duplicate warning",
                         self.ok("catchup", "2020-01-01").stdout)


if __name__ == "__main__":
    unittest.main()
