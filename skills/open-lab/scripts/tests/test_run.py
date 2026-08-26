#!/usr/bin/env python3
"""Tests for run.py. Each test builds a throwaway git repo in a temp dir and
drives the script as a subprocess, the way a Director would.

Run from open-lab/scripts/tests/:  python3 -m unittest
"""
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ID_LINE = re.compile(r"^C-(?:[a-z0-9][a-z0-9-]*-)?\d+$")
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
                      "manual": {"model": "worker-a"},
                      "nameless": {"command": "/bin/echo {prompt}"}},
            "tools": ["python3"]}))
        self.problem = self.root / "problems" / "demo"
        (self.problem / "claims").mkdir(parents=True)
        (self.problem / "README.md").write_text("# demo\n")
        (self.problem / "STATUS.md").write_text("# Status: demo\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "seed")

    # -- driving the scripts ---------------------------------------------
    def script(self, path, *args, cwd=None, env=None):
        return subprocess.run([sys.executable, str(path)] + list(args),
                              cwd=str(cwd or self.problem), capture_output=True,
                              text=True, env=dict(os.environ, **(env or {})))

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
        ids = [l.strip() for l in r.stdout.splitlines() if ID_LINE.match(l.strip())]
        return ids[0] if ids else r.stdout.strip().splitlines()[-1]

    # -- lab fixtures ----------------------------------------------------
    def brief(self, text="Count the caps.", name="b1.md"):
        d = self.problem / "briefs"
        d.mkdir(exist_ok=True)
        p = d / name
        p.write_text("# Brief: demo\n\n## Goal\n\n%s\n" % text)
        return p

    def dispatch(self, brief=None, extra=(), expect_warning=None):
        args = ["new", "--brief", str(brief or self.brief()), "--no-launch",
                "--role", "manual"]
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

    def test_second_dispatch_of_the_same_brief_is_refused(self):
        """F-026: a retry that fired twice dispatched the same question
        twice; the old warning was scrolled past."""
        b = self.brief()
        self.dispatch(b)
        err = self.refused("new", "--brief", str(b), "--no-launch",
                           "--role", "manual")
        self.assertIn("same brief", err)
        self.dispatch(b, extra=["--force"], expect_warning="same brief")

    def test_role_on_hold_refused_until_its_date(self):
        """F-007: a brief was written for a role with no quota; the fact lived
        in a note. A hold is a date, so it lifts itself."""
        cfg = json.loads((self.root / "lab.json").read_text())
        cfg["roles"]["manual"].update(unavailable_until="2999-01-01",
                                      note="quota exhausted")
        (self.root / "lab.json").write_text(json.dumps(cfg))
        err = self.refused("new", "--brief", str(self.brief()), "--no-launch",
                           "--role", "manual")
        self.assertIn("quota exhausted", err)
        self.assertIn("manual until 2999-01-01",
                      self.ok("catchup", "2020-01-01").stdout)
        cfg["roles"]["manual"]["unavailable_until"] = "2000-01-01"
        cfg["roles"]["manual"]["note"] = "for: small jobs. not for: long reads"
        (self.root / "lab.json").write_text(json.dumps(cfg))
        _, r = self.dispatch()
        self.assertIn("not for: long reads", r.stdout)    # F-008: read at dispatch
        cfg["roles"]["manual"] = {"model": "worker-a", "available": False}
        (self.root / "lab.json").write_text(json.dumps(cfg))
        err = self.refused("new", "--brief", str(self.brief("b", "b2.md")),
                           "--no-launch", "--role", "manual")
        self.assertIn("goes stale", err)

    def sleeper_role(self, seconds, **limits):
        cfg = json.loads((self.root / "lab.json").read_text())
        cfg["roles"]["sleeper"] = dict(
            {"model": "worker-z",
             "command": "/bin/sh -c 'sleep %s' {prompt}" % seconds}, **limits)
        (self.root / "lab.json").write_text(json.dumps(cfg))

    def test_breach_is_recorded_and_reported_never_enforced(self):
        """F-002/F-028: the wait once had its eyes closed. A worker over
        budget is reported at every step; killing it is the Investigator's
        call, so it finishes on its own here."""
        self.sleeper_role(2, worker_timeout=1)
        r = self.ok("new", "--brief", str(self.brief()), "--role", "sleeper",
                    "--memory-gb", "0.000001", env={"LAB_POLL_SECONDS": "0.2"})
        rid = r.stdout.split()[0]
        self.assertIn("Investigator decides", r.stdout)
        e = json.loads((self.problem / "runs" / rid / "execution.json").read_text())
        self.assertEqual(e["exit"], 0)                      # not killed
        self.assertEqual(sorted(b["kind"] for b in e["breaches"]),
                         ["memory", "timeout"])
        self.assertGreater(e["peak_rss_mb"], 0)
        self.assertEqual(e["limits"]["worker_timeout"], 1)
        # An open run with a breach is named at every step until it ends.
        rid2, _ = self.dispatch(self.brief("b", "b2.md"))
        sleeper = subprocess.Popen(["/bin/sleep", "60"])
        self.addCleanup(sleeper.kill)
        (self.problem / "runs" / rid2 / "execution.json").write_text(json.dumps(
            {"run": rid2, "pid": sleeper.pid, "start": "now",
             "breaches": [{"kind": "memory", "at": "t", "seen": 12.5,
                           "unit": "GB", "limit": 10}]}))
        out = self.ok("catchup", "2020-01-01").stdout
        self.assertIn("%s: over its memory budget" % rid2, out)
        self.assertIn("kill %d" % sleeper.pid, out)

    def test_detach_returns_at_once_and_ingest_waits_for_the_exit(self):
        """F-015: chained dispatches serialized because new never returned."""
        self.sleeper_role(2)
        t0 = time.time()
        r = self.ok("new", "--brief", str(self.brief()), "--role", "sleeper",
                    "--detach", env={"LAB_POLL_SECONDS": "0.2"})
        self.assertLess(time.time() - t0, 1.5)
        self.assertIn("Detached", r.stdout)
        rid = r.stdout.split()[0]
        ex = self.problem / "runs" / rid / "execution.json"
        for _ in range(50):
            if "pid" in json.loads(ex.read_text()):
                break
            time.sleep(0.1)
        self.packet(rid)
        err = self.refused("ingest", rid)
        self.assertIn("still running", err)
        for _ in range(60):
            if json.loads(ex.read_text()).get("end"):
                break
            time.sleep(0.1)
        self.assertEqual(json.loads(ex.read_text())["exit"], 0)
        self.ok("ingest", rid)

    def test_no_launch_refused_for_a_role_that_launches(self):
        """F-019: --no-launch on a lab.json role left a run open with no
        worker."""
        err = self.refused("new", "--brief", str(self.brief()), "--no-launch",
                           "--role", "technician")
        self.assertIn("--no-launch", err)
        self.assertEqual(list((self.problem / "runs").glob("R-*"))
                         if (self.problem / "runs").exists() else [], [])

    def test_live_worker_is_never_overridden(self):
        """F-011: --worker-done once bypassed a live process; the orphan kept
        writing into a filed run."""
        rid, _ = self.dispatch()
        sleeper = subprocess.Popen(["/bin/sleep", "60"])
        self.addCleanup(sleeper.kill)
        (self.problem / "runs" / rid / "execution.json").write_text(json.dumps(
            {"pid": sleeper.pid, "start": "now"}))
        self.packet(rid)
        err = self.refused("ingest", rid, "--worker-done")
        self.assertIn("kill %d" % sleeper.pid, err)
        sleeper.kill(); sleeper.wait()
        self.ok("ingest", rid, "--worker-done")

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

    def test_replay_runs_the_whole_block(self):
        """F-001: the gate once ran only the first line of a block. Every
        line runs, and a failing line fails the replay even when the last
        line exits clean."""
        rid, _ = self.dispatch()
        self.packet(rid, command="printf '%s\\n' FIRST_LINE_OK\n"
                                 "    printf '%s\\n' CHECK_OK")
        self.ok("ingest", rid)
        rec = self.ingest_json(rid)
        self.assertIs(rec["replayed"], True)
        self.assertEqual(rec["replay"]["command"].count("\n"), 1)

        rid, _ = self.dispatch(self.brief("Again.", "b2.md"))
        self.packet(rid, command="false\n    printf '%s\\n' CHECK_OK")
        self.ok("ingest", rid)
        self.assertIs(self.ingest_json(rid)["replayed"], False)

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

    def test_checks_fills_reviewed_and_can_be_overridden(self):
        """F-017/F-021: no worker was ever told about `reviewed`, so every
        check left its target flagged. --checks at dispatch fills it in;
        --reviewed at ingest corrects a packet that named the wrong run."""
        first, _ = self.dispatch(self.brief("Prove the bound.", "b1.md"))
        self.packet(first)
        self.ok("ingest", first)
        err = self.refused("new", "--brief", str(self.brief("x", "bx.md")),
                           "--no-launch", "--role", "manual", "--checks", "R-042")
        self.assertIn("no ingested run R-042", err)

        err = self.refused("new", "--brief", str(self.brief("Referee.", "b2.md")),
                           "--no-launch", "--role", "manual", "--checks", first)
        self.assertIn("same", err)                          # F-013: same model
        second, _ = self.dispatch(self.brief("Referee.", "b2.md"),
                                  extra=["--model", "worker-b",
                                         "--checks", first])
        self.assertEqual(self.dispatch_json(second)["checks"], first)
        self.packet(second, headline="It holds.")
        r = self.ok("ingest", second)
        self.assertIn("filled from the dispatch", r.stdout)
        self.assertEqual(self.ingest_json(first)["reviewed_by"], [second])

        third, _ = self.dispatch(self.brief("Referee again.", "b3.md"),
                                 extra=["--model", "worker-c"])
        self.packet(third, headline="Still holds.", ret={"reviewed": ["R-099"]})
        self.refused("ingest", third)
        r = self.ok("ingest", third, "--reviewed", first)
        self.assertIn("set by the Director at ingest", r.stdout)
        self.assertEqual(sorted(self.ingest_json(first)["reviewed_by"]),
                         sorted([second, third]))

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

    def test_status_lint_names_proposed_claims_written_as_fact(self):
        """F-018, eight times: a proposed claim stated as settled and refuted
        half an hour later. The lint names the sentence; the Director labels
        it by hand — nothing rewrites STATUS.md."""
        rid, _ = self.dispatch()
        self.packet(rid, ret={"claims_proposed": ["The bound is 17."]})
        r = self.ok("ingest", rid)
        self.assertIn("1 run(s) ingested since: %s" % rid, r.stdout)
        status = self.problem / "STATUS.md"
        status.write_text("# Status: demo\n\n## Bottom line\n\nBy C-001, the "
                          "bound is 17.\n\n## Ruled out\n\nC-001 is not a "
                          "lower bound.\n")
        out = self.ok("catchup", "2020-01-01").stdout
        self.assertIn("states as settled what is only proposed", out)
        self.assertIn('- C-001 in "Bottom line"', out)
        self.assertNotIn('"Ruled out"', out)
        status.write_text("# Status: demo\n\n## Bottom line\n\nBy C-001 "
                          "(proposed, unreviewed), the bound is 17.\n")
        self.assertNotIn("only proposed", self.ok("catchup", "2020-01-01").stdout)

    def test_rotation_is_proposed_after_n_ingests_in_one_session(self):
        """F-020: nothing said when a session had run long. The notice is
        printed; rotation itself is the Investigator's call."""
        cfg = json.loads((self.root / "lab.json").read_text())
        cfg["machine"] = {"rotate_after_ingests": 2}
        (self.root / "lab.json").write_text(json.dumps(cfg))
        env = {"LAB_SESSION": "sess-1"}
        for i in range(2):
            rid, _ = self.dispatch(self.brief("q%d" % i, "b%d.md" % i))
            self.packet(rid)
            out = self.ok("ingest", rid, env=env).stdout
        self.assertEqual(self.ingest_json(rid)["director_session"], "sess-1")
        self.assertIn("Propose rotation", out)
        rid, _ = self.dispatch(self.brief("q9", "b9.md"))
        self.packet(rid)
        self.assertNotIn("Propose rotation",
                         self.ok("ingest", rid, env={"LAB_SESSION": "sess-2"}).stdout)

    def test_stale_baselines_are_named_by_catchup(self):
        """F-016: the baseline stood still while the public board moved."""
        src = self.problem / "sources"
        src.mkdir()
        (src / "MANIFEST.md").write_text(
            "- knauer_labs.csv — baseline, Knauer 2004 table, fetched "
            "2020-01-01, sha256 abc\n"
            "- board.json — baseline, live board, fetched %s, sha256 def\n"
            "- paper.pdf — Packebusch–Mertens 2016, sha256 123\n"
            % time.strftime("%Y-%m-%d", time.gmtime()))
        out = self.ok("catchup", "2020-01-01").stdout
        self.assertIn("Baselines older than 30 days", out)
        self.assertIn("knauer_labs.csv", out)
        self.assertNotIn("board.json", out)

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
        # The Director rewrites belief documents mid-flight, any subject line,
        # naming the path — the guard refuses -A while a run is open.
        (self.problem / "STATUS.md").write_text("# Status: demo\n\nRewritten.\n")
        git(self.root, "add", "problems/demo/STATUS.md")
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

    def test_another_problems_live_run_does_not_implicate_a_worker(self):
        """Six problems ran workers at once; a live worker in one problem
        was blamed on the run under ingest in another."""
        rid, _ = self.dispatch()
        self.packet(rid)
        other = self.root / "problems" / "other" / "runs" / "R-003" / "packet"
        other.mkdir(parents=True)
        (self.root / "problems" / "other" / "README.md").write_text("# other\n")
        git(self.root, "add", "problems/other/README.md")
        git(self.root, "commit", "-q", "-m", "second problem")
        (other / "RESULT.md").write_text("# VERDICT: PENDING\n")  # uncommitted
        self.ok("ingest", rid)
        self.assertEqual(self.dispatch_json(rid)["status"], "ingested")

    def test_hand_commit_of_an_open_run_is_refused(self):
        """F-010: seven hand commits in one day swept open runs' files into
        unrelated amendments. The guard is installed at the first dispatch
        and lets the scripts' own commits through."""
        rid, _ = self.dispatch()
        hook = self.root / ".git" / "hooks" / "pre-commit"
        self.assertIn("guard-commit", hook.read_text())
        self.packet(rid)
        (self.problem / "STATUS.md").write_text("# Status: demo\n\nEdited.\n")
        git(self.root, "add", "-A")
        r = subprocess.run(["git", "commit", "-q", "-m", "lab.json + memory"],
                           cwd=str(self.root), capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(rid, r.stderr)
        self.assertIn("still open", r.stderr)
        git(self.root, "reset", "-q")
        git(self.root, "add", "problems/demo/STATUS.md")
        self.assertEqual(git(self.root, "commit", "-q", "-m", "status").returncode, 0)
        self.ok("ingest", rid)                       # the script's own commit passes
        self.assertEqual(self.dispatch_json(rid)["status"], "ingested")
        (self.problem / "runs" / rid / "note.txt").write_text("later\n")
        git(self.root, "add", "-A")
        self.assertEqual(git(self.root, "commit", "-q", "-m", "closed run").returncode, 0)

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
        """F-009: with nothing on record, the reason is the Director's to
        give, and it goes first."""
        rid, _ = self.dispatch()
        err = self.refused("ingest", rid, "--record-broken")
        self.assertIn("--reason", err)
        r = self.ok("ingest", rid, "--record-broken",
                    "--reason", "session quota ran out before launch")
        self.assertIn("HARNESS-FAILURE", r.stdout)
        self.assertEqual(self.ingest_json(rid)["verdict"], "HARNESS-FAILURE")
        self.assertIn("HARNESS-FAILURE", self.log())
        self.assertIn("quota ran out", self.log())

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


class TestHousekeeping(LabCase):

    def test_catchup_with_no_date_uses_the_last_week(self):
        """A session that opens by asking the Director to pick a date starts
        by getting it wrong."""
        rid, _ = self.dispatch()
        self.packet(rid)
        self.ok("ingest", rid)
        out = self.ok("catchup").stdout
        self.assertIn("Since the last seven days", out)
        self.assertIn("%s PASS" % rid, out)

    def test_dispatch_writes_and_commits_a_gitignore(self):
        """A byte-compiled file left under a run counts against the worker
        that never wrote it."""
        self.assertFalse((self.root / ".gitignore").exists())
        self.dispatch()
        text = (self.root / ".gitignore").read_text()
        self.assertIn("__pycache__/", text)
        self.assertIn("*.pyc", text)
        self.assertEqual(git(self.root, "status", "--porcelain").stdout.strip(), "")

    def test_an_existing_gitignore_is_added_to_not_replaced(self):
        (self.root / ".gitignore").write_text("secrets.env\n")
        self.dispatch()
        text = (self.root / ".gitignore").read_text()
        self.assertIn("secrets.env", text)
        self.assertIn("__pycache__/", text)
        self.dispatch(self.brief("Again.", "b2.md"))          # idempotent
        self.assertEqual((self.root / ".gitignore").read_text(), text)

    def echoing_role(self, line, pattern=None):
        cfg = json.loads((self.root / "lab.json").read_text())
        cfg["roles"]["echoer"] = {"model": "worker-a",
                                  "command": "/bin/sh -c 'echo \"%s\"' {prompt}"
                                             % line}
        if pattern:
            cfg["roles"]["echoer"]["usage_pattern"] = pattern
        (self.root / "lab.json").write_text(json.dumps(cfg))

    def test_token_counts_are_read_however_the_worker_prints_them(self):
        """A count reported in one shape only is a count missing from every
        other worker's record."""
        shapes = [("tokens used: 1,234", "1,234"), ("tokens: 987", "987"),
                  ("12.5K tokens", "12.5K")]
        for i, (line, expected) in enumerate(shapes):
            self.echoing_role(line)
            r = self.ok("new", "--brief", str(self.brief("Shape %d." % i,
                                                         "b%d.md" % i)),
                        "--role", "echoer")
            rid = r.stdout.split()[0]
            e = json.loads((self.problem / "runs" / rid /
                            "execution.json").read_text())
            self.assertEqual(e["usage"], {"tokens": expected}, line)
        # A role's own named-group pattern still wins.
        self.echoing_role("spent 5 credits", r"spent (?P<cost>\d+) credits")
        r = self.ok("new", "--brief", str(self.brief("Own pattern.", "bp.md")),
                    "--role", "echoer")
        rid = r.stdout.split()[0]
        e = json.loads((self.problem / "runs" / rid / "execution.json").read_text())
        self.assertEqual(e["usage"], {"cost": "5"})


class TestLargeOutputs(LabCase):
    """A file committed once is in the history for good, and a host refuses
    one past a certain size: after such an ingest the record cannot be
    pushed at all."""

    def cap(self, mb):
        cfg = json.loads((self.root / "lab.json").read_text())
        cfg["commits"] = {"max_mb": mb}
        (self.root / "lab.json").write_text(json.dumps(cfg))
        git(self.root, "add", "lab.json")
        git(self.root, "commit", "-q", "-m", "cap on what a commit may carry")

    def outputs(self, rid, big=200 * 1024, small=200):
        d = self.problem / "runs" / rid / "packet"
        d.mkdir(parents=True, exist_ok=True)
        (d / "big.bin").write_bytes(b"x" * big)
        (d / "small.txt").write_bytes(b"y" * small)
        return d / "big.bin", d / "small.txt"

    def tracked(self, path):
        rel = str(Path(path).relative_to(self.root))
        return git(self.root, "ls-files", "--", rel).stdout.strip() == rel

    def test_an_oversized_output_stays_on_disk_pinned_by_hash(self):
        self.cap(0.05)                       # ~52 KB
        rid, _ = self.dispatch()
        big, small = self.outputs(rid)
        self.packet(rid)
        r = self.ok("ingest", rid)
        self.assertIn("stays on disk", r.stdout)
        self.assertIn("big.bin", r.stdout)

        self.assertTrue(big.exists(), "the output was not left where it was")
        self.assertFalse(self.tracked(big), "the oversized file was committed")
        self.assertTrue(self.tracked(small))
        ignore = (self.root / ".gitignore").read_text()
        self.assertIn("pinned by hash in ingest.json", ignore)
        self.assertIn("/problems/demo/runs/%s/packet/big.bin" % rid, ignore)

        held = self.ingest_json(rid)["large_files"]
        self.assertEqual([h["path"] for h in held],
                         ["problems/demo/runs/%s/packet/big.bin" % rid])
        self.assertEqual(held[0]["bytes"], 200 * 1024)
        self.assertEqual(held[0]["sha256"],
                         hashlib.sha256(big.read_bytes()).hexdigest())
        # Ignored files are not uncommitted work: the tree is clean, and a
        # later `git add -A` cannot sweep the file in either.
        self.assertEqual(git(self.root, "status", "--porcelain").stdout.strip(), "")
        git(self.root, "add", "-A")
        self.assertFalse(self.tracked(big))

    def test_under_the_default_cap_everything_is_committed(self):
        rid, _ = self.dispatch()
        big, small = self.outputs(rid)
        self.packet(rid)
        r = self.ok("ingest", rid)
        self.assertNotIn("stays on disk", r.stdout)
        self.assertTrue(self.tracked(big))
        self.assertTrue(self.tracked(small))
        self.assertEqual(self.ingest_json(rid)["large_files"], [])


class TestTranscripts(LabCase):
    """The worker's own session file, copied into the record at ingest. Its
    stdout is in worker.log; the reasoning and tool calls behind a result
    live in one command's private store, on one machine, pruned on its own
    schedule."""

    def setUp(self):
        super().setUp()
        self.store = Path(tempfile.mkdtemp(prefix="labsessions-"))
        self.addCleanup(shutil.rmtree, self.store, ignore_errors=True)

    def configure(self, transcript=None, **lab):
        cfg = json.loads((self.root / "lab.json").read_text())
        if transcript is not None:
            cfg["roles"]["manual"]["transcript"] = transcript
        cfg.update(lab)
        (self.root / "lab.json").write_text(json.dumps(cfg))

    def session(self, path, cwd=None, body="thought\n"):
        """A session file in the shape these stores write: JSON per line,
        the working directory in the first one."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"type": "meta", "cwd": str(cwd or "")})
                     + "\n" + json.dumps({"type": "text", "body": body}) + "\n")
        return p

    def rundir(self, rid):
        return (self.problem / "runs" / rid).resolve()

    def transcript_json(self, rid):
        return self.ingest_json(rid)["transcript"]

    def stored_bytes(self, rid):
        return gzip.decompress((self.problem / "runs" / rid /
                                "session.jsonl.gz").read_bytes())

    def sha(self, path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def test_first_line_cwd_picks_this_runs_session_not_the_newest(self):
        self.configure({"glob": str(self.store / "*.jsonl"),
                        "match": "first-line-cwd"})
        rid, _ = self.dispatch()
        mine = self.session(self.store / "a.jsonl", cwd=self.rundir(rid))
        theirs = self.session(self.store / "b.jsonl", cwd=self.store,
                              body="another run's session\n")
        os.utime(theirs, (time.time() + 5, time.time() + 5))   # newer
        self.packet(rid)
        r = self.ok("ingest", rid)
        self.assertIn("Transcript stored", r.stdout)
        self.assertEqual(self.stored_bytes(rid), mine.read_bytes())
        rec = self.transcript_json(rid)
        self.assertEqual(rec["sha256"], self.sha(mine))
        self.assertEqual(rec["bytes"], mine.stat().st_size)
        self.assertIs(rec["stored"], True)
        self.assertEqual(rec["source"], str(mine))
        # It went into the record with the run, not left on the disk.
        path = "problems/demo/runs/%s/session.jsonl.gz" % rid
        self.assertEqual(git(self.root, "ls-files", "--", path).stdout.strip(),
                         path)
        self.assertIn("%s ingested" % rid,
                      git(self.root, "log", "-1", "--name-only",
                          "--pretty=%s", "--", path).stdout)

    def test_path_rule_finds_a_folder_named_after_the_working_directory(self):
        self.configure({"glob": str(self.store / "{cwd_dashed}" / "*.jsonl"),
                        "match": "path"})
        rid, _ = self.dispatch()
        dashed = str(self.rundir(rid)).replace("/", "-")
        mine = self.session(self.store / dashed / "s.jsonl")
        self.packet(rid)
        self.ok("ingest", rid)
        self.assertEqual(self.stored_bytes(rid), mine.read_bytes())
        self.assertEqual(self.transcript_json(rid)["sha256"], self.sha(mine))

    def test_over_the_cap_it_is_described_but_not_copied(self):
        self.configure({"glob": str(self.store / "*.jsonl"),
                        "match": "first-line-cwd"},
                       transcripts={"max_mb": 0.000001})
        rid, _ = self.dispatch()
        mine = self.session(self.store / "a.jsonl", cwd=self.rundir(rid))
        self.packet(rid)
        r = self.ok("ingest", rid)
        self.assertIn("over transcripts.max_mb", r.stdout)
        self.assertIn(str(mine), r.stdout)                  # where it lives
        rec = self.transcript_json(rid)
        self.assertIs(rec["stored"], False)
        self.assertEqual(rec["sha256"], self.sha(mine))
        self.assertGreater(rec["gzipped_bytes"], 0)
        self.assertFalse((self.problem / "runs" / rid /
                          "session.jsonl.gz").exists())

    def test_the_flag_wins_over_discovery(self):
        """A worker the Director drove itself leaves its session where no
        role rule looks."""
        self.configure({"glob": str(self.store / "found-*.jsonl"),
                        "match": "first-line-cwd"})
        rid, _ = self.dispatch()
        self.session(self.store / "found-a.jsonl", cwd=self.rundir(rid))
        named = self.session(self.store / "by-hand.jsonl", body="the real one\n")
        self.packet(rid)
        self.ok("ingest", rid, "--transcript", str(named))
        self.assertEqual(self.stored_bytes(rid), named.read_bytes())
        self.assertEqual(self.transcript_json(rid)["source"], str(named))
        err = self.refused("ingest", "R-404", "--transcript", str(named))
        self.assertIn("no run R-404", err)

    def test_a_run_filed_broken_keeps_its_transcript_too(self):
        self.configure({"glob": str(self.store / "*.jsonl"),
                        "match": "first-line-cwd"})
        rid, _ = self.dispatch()
        mine = self.session(self.store / "a.jsonl", cwd=self.rundir(rid))
        self.packet(rid, ret_text="{ not json at all")
        self.refused("ingest", rid)
        self.ok("ingest", rid, "--record-broken")
        self.assertEqual(self.ingest_json(rid)["verdict"], "UNINGESTABLE")
        self.assertEqual(self.stored_bytes(rid), mine.read_bytes())
        self.assertIs(self.transcript_json(rid)["stored"], True)

    def test_a_nested_working_directory_is_found_too(self):
        """Some commands put the working directory one level down in their
        first record; a rule that knew only the flat shape found nothing."""
        self.configure({"glob": str(self.store / "*.jsonl"),
                        "match": "first-line-cwd"})
        rid, _ = self.dispatch()
        mine = self.store / "nested.jsonl"
        mine.write_text(json.dumps({"type": "meta",
                                    "payload": {"cwd": str(self.rundir(rid))}})
                        + "\n" + json.dumps({"type": "text"}) + "\n")
        self.packet(rid)
        self.ok("ingest", rid)
        self.assertEqual(self.stored_bytes(rid), mine.read_bytes())

    def test_a_transcript_can_be_attached_after_the_run_is_on_record(self):
        """Discovery runs at ingest, when the session file is freshest. A
        rule that was wrong then would otherwise lose the reasoning behind a
        filed run for good."""
        rid, _ = self.dispatch()
        mine = self.session(self.store / "a.jsonl", cwd=self.rundir(rid))
        err = self.refused("transcript", rid)
        self.assertIn("no ingest record", err)

        self.packet(rid)
        self.ok("ingest", rid)                       # no rule yet: none stored
        self.assertIsNone(self.transcript_json(rid))
        self.configure({"glob": str(self.store / "*.jsonl"),
                        "match": "first-line-cwd"})
        r = self.ok("transcript", rid)
        self.assertIn("transcript on record", r.stdout)
        self.assertEqual(self.stored_bytes(rid), mine.read_bytes())
        self.assertEqual(self.transcript_json(rid)["sha256"], self.sha(mine))
        self.assertIn("%s: transcript attached" % rid, self.log())

        err = self.refused("transcript", rid)
        self.assertIn("--replace", err)
        other = self.session(self.store / "by-hand.jsonl", body="the real one\n")
        self.ok("transcript", rid, "--path", str(other), "--replace")
        self.assertEqual(self.stored_bytes(rid), other.read_bytes())
        self.assertEqual(self.transcript_json(rid)["source"], str(other))

    def test_runs_missing_a_transcript_are_named_by_catchup(self):
        self.configure({"glob": str(self.store / "nothing-*.jsonl"),
                        "match": "path"})
        rid, _ = self.dispatch()
        self.packet(rid)
        r = self.ok("ingest", rid)
        self.assertIn("No transcript found", r.stdout)
        out = self.ok("catchup", "2020-01-01").stdout
        self.assertIn("no transcript stored", out)
        self.assertIn(rid, out.split("Attention:")[1])
        # Closable: attach one and the line goes.
        named = self.session(self.store / "by-hand.jsonl")
        self.ok("transcript", rid, "--path", str(named))
        self.assertNotIn("no transcript stored",
                         self.ok("catchup", "2020-01-01").stdout)

    def test_a_role_with_no_rule_files_the_run_without_one(self):
        rid, _ = self.dispatch()
        self.session(self.store / "a.jsonl", cwd=self.rundir(rid))
        self.packet(rid)
        r = self.ok("ingest", rid)
        self.assertIsNone(self.transcript_json(rid))
        self.assertNotIn("Transcript stored", r.stdout)
        self.assertIn("none on record", self.ok("lint", rid).stdout)
        # Nothing to flag either: the lab never said where to look.
        self.assertNotIn("no transcript stored",
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
