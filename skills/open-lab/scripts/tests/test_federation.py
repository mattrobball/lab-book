#!/usr/bin/env python3
"""Tests for several investigators in one lab: tags, branches, namespaced
IDs, ownership, reading the others without merging, and the meeting.

Each test builds a bare remote and two clones with different git users, and
drives the scripts as a subprocess, the way two Directors on two machines
would.

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

SCRIPTS = Path(__file__).resolve().parent.parent
RUN = SCRIPTS / "run.py"
CLAIMS = SCRIPTS / "claims.py"


def git(cwd, *args, check=True):
    return subprocess.run(["git"] + list(args), cwd=str(cwd), check=check,
                          capture_output=True, text=True)


class FederationCase(unittest.TestCase):
    """A bare remote, a seeded lab on main, and two clones: alice and bob."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="labfed-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.remote = self.tmp / "origin.git"
        git(self.tmp, "init", "-q", "--bare", str(self.remote))

        seed = self.tmp / "seed"
        seed.mkdir()
        git(seed, "init", "-q")
        git(seed, "symbolic-ref", "HEAD", "refs/heads/main")
        git(seed, "config", "user.name", "Seed Keeper")
        git(seed, "config", "user.email", "seed@example.invalid")
        (seed / "lab.json").write_text(json.dumps(
            {"roles": {"manual": {"model": "worker-a"}}, "tools": ["python3"]}))
        problem = seed / "problems" / "demo"
        (problem / "claims").mkdir(parents=True)
        (problem / "README.md").write_text("# demo\n")
        (problem / "STATUS.md").write_text("# Status: demo\n\n## Bottom line\n\n"
                                           "Nothing settled yet.\n")
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "seed")
        git(seed, "remote", "add", "origin", str(self.remote))
        git(seed, "push", "-q", "origin", "main")
        git(self.remote, "symbolic-ref", "HEAD", "refs/heads/main")

        self.alice = self.clone("alice", "Alice")
        self.bob = self.clone("bob", "Bob")

    # -- the lab ---------------------------------------------------------
    def clone(self, name, user):
        d = self.tmp / name
        git(self.tmp, "clone", "-q", str(self.remote), str(d))
        git(d, "config", "user.name", user)
        git(d, "config", "user.email", "%s@example.invalid" % name)
        return d

    def problem(self, clone):
        return clone / "problems" / "demo"

    # -- driving the scripts ---------------------------------------------
    def script(self, path, clone, *args, cwd=None):
        return subprocess.run([sys.executable, str(path)] + list(args),
                              cwd=str(cwd or self.problem(clone)),
                              capture_output=True, text=True, env=dict(os.environ))

    def run_py(self, clone, *args, **kw):
        return self.script(RUN, clone, *args, **kw)

    def ok(self, clone, *args, **kw):
        r = self.run_py(clone, *args, **kw)
        self.assertEqual(r.returncode, 0, "expected success, got:\n%s%s"
                         % (r.stdout, r.stderr))
        return r

    def refused(self, clone, *args, **kw):
        r = self.run_py(clone, *args, **kw)
        self.assertEqual(r.returncode, 2, "expected a refusal, got:\n%s%s"
                         % (r.stdout, r.stderr))
        self.assertTrue(r.stderr.startswith("Refused:"), r.stderr)
        return r.stderr

    def claims_ok(self, clone, *args, **kw):
        r = self.script(CLAIMS, clone, *args, **kw)
        self.assertEqual(r.returncode, 0, "expected success, got:\n%s%s"
                         % (r.stdout, r.stderr))
        return r

    def join(self, clone):
        return self.ok(clone, "join", cwd=clone)

    # -- fixtures --------------------------------------------------------
    def brief(self, clone, text=None, name="b1.md"):
        d = self.problem(clone) / "briefs"
        d.mkdir(exist_ok=True)
        p = d / name
        p.write_text("# Brief: demo\n\n## Goal\n\n%s\n"
                     % (text or "Count the caps, question %s." % name))
        return p

    def dispatch(self, clone, brief=None, name="b1.md", extra=()):
        b = brief or self.brief(clone, name=name)
        r = self.ok(clone, "new", "--brief", str(b), "--no-launch",
                    "--role", "manual", *extra)
        return r.stdout.split()[0], r

    def packet(self, clone, rid, headline="The check ran clean.", proposed=()):
        d = self.problem(clone) / "runs" / rid / "packet"
        d.mkdir(parents=True, exist_ok=True)
        (d / "RESULT.md").write_text(
            "# VERDICT: PASS\n\n%s\n\n## What was done\n\nRan it.\n\n"
            "## Not claimed\n\nNothing else.\n\n## Leads\n\nNone.\n\n"
            "## Validation\n\n    printf '%%s\\n' CHECK_OK\n\nIt prints:\n\n"
            "    CHECK_OK\n" % headline)
        (d / "RETURN.json").write_text(json.dumps(
            {"headline": headline, "exits": ["checked"], "validation": "replay",
             "machine_markers": ["CHECK_OK"], "claims_used": [],
             "claims_proposed": list(proposed)}))

    def work(self, clone, name="b1.md", headline="It ran.", proposed=()):
        """One whole run on one clone: dispatch, packet, ingest."""
        rid, _ = self.dispatch(clone, name=name)
        self.packet(clone, rid, headline=headline, proposed=proposed)
        self.ok(clone, "ingest", rid)
        return rid

    def lab_json(self, clone):
        return json.loads((clone / "lab.json").read_text())

    def branch(self, clone):
        return git(clone, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def dispatch_json(self, clone, rid):
        return json.loads((self.problem(clone) / "runs" / rid /
                           "dispatch.json").read_text())


class TestJoin(FederationCase):

    def test_join_registers_creates_the_branch_and_is_idempotent(self):
        r = self.join(self.alice)
        self.assertIn("Joined as alice", r.stdout)
        self.assertEqual(self.branch(self.alice), "lab/alice")
        reg = self.lab_json(self.alice)["investigators"]
        self.assertEqual(reg["alice"]["name"], "Alice")
        self.assertIn("joined", reg["alice"])
        self.assertIn("host", reg["alice"])
        # Committed on the investigator's own branch, and pushed.
        self.assertIn("join: alice", git(self.alice, "log", "--pretty=%s").stdout)
        self.assertTrue(git(self.alice, "rev-parse", "--verify",
                            "origin/lab/alice", check=False).returncode == 0)

        again = self.join(self.alice)
        self.assertIn("Already registered", again.stdout)
        self.assertEqual(self.branch(self.alice), "lab/alice")
        self.assertEqual(list(self.lab_json(self.alice)["investigators"]),
                         ["alice"])

        version = re.search(r'version:\s*"?([0-9][^"\s]*)"?',
                            (SCRIPTS.parent / "SKILL.md").read_text()).group(1)
        self.assertEqual(self.lab_json(self.alice)["kit_version"], version)

        who = self.ok(self.alice, "whoami", cwd=self.alice).stdout
        self.assertIn("tag: alice", who)
        self.assertIn("branch: lab/alice", who)
        self.assertIn("unpushed: 0", who)

    def test_join_scaffolds_the_ignore_file_and_credits_by_tag(self):
        self.join(self.alice)
        text = (self.alice / ".gitignore").read_text()
        self.assertIn("__pycache__/", text)
        self.assertIn("*.pyc", text)
        self.assertIn(".gitignore", git(self.alice, "show", "--name-only",
                                        "--pretty=", "HEAD").stdout)
        # With an investigator on record, who is doing this is no longer a
        # question anyone has to answer twice.
        cid = self.claims_ok(self.alice, "new", "--statement",
                             "A holds.").stdout.splitlines()[0].strip()
        view = (self.problem(self.alice) / "claims" / (cid + ".md")).read_text()
        self.assertIn("**Discovered by:** alice", view)
        self.ok(self.alice, "note", "--headline", "A decision",
                "--body", "Taken in conversation.")
        entry = sorted((self.problem(self.alice) / "notebook" /
                        "entries").glob("N-*.md"))[-1].read_text()
        self.assertIn("**Actor:** alice", entry)

    def test_a_tag_taken_by_someone_else_is_refused(self):
        self.join(self.alice)
        git(self.alice, "config", "user.name", "ALICE")   # same tag
        err = self.refused(self.alice, "join", cwd=self.alice)
        self.assertIn("already taken", err)
        self.assertIn("alice", err)

    def test_a_lab_nobody_joined_works_exactly_as_before(self):
        """The rules arrive with the first join and not before: one
        investigator's lab keeps untagged IDs, one ledger, any branch."""
        self.assertEqual(self.branch(self.bob), "main")
        rid = self.work(self.bob)
        self.assertEqual(rid, "R-001")
        self.assertEqual(self.branch(self.bob), "main")
        ledger = self.problem(self.bob) / "claims" / "ledger.jsonl"
        self.dispatch(self.bob, name="b2.md")
        self.assertIn("R-002", [p.name for p in
                                (self.problem(self.bob) / "runs").iterdir()])
        self.assertFalse((self.problem(self.bob) / "claims" /
                          "ledger-bob.jsonl").exists())
        self.assertNotIn("investigators", self.lab_json(self.bob))


class TestBranchRule(FederationCase):

    def test_writes_off_the_own_branch_are_refused_with_the_fix(self):
        self.join(self.alice)
        git(self.alice, "checkout", "-q", "main")
        err = self.refused(self.alice, "new", "--brief",
                           str(self.brief(self.alice)), "--no-launch",
                           "--role", "manual")
        self.assertIn("run.py join", err)
        self.assertIn("lab/alice", err)
        err = self.refused(self.alice, "note", "--headline", "h",
                           "--body", "b", "--actor", "director")
        self.assertIn("run.py join", err)
        r = self.script(CLAIMS, self.alice, "new", "--statement", "A holds.",
                        "--actor", "director")
        self.assertEqual(r.returncode, 2)
        self.assertIn("run.py join", r.stderr)
        # Read-only commands work wherever you are.
        self.ok(self.alice, "catchup", "2020-01-01")
        self.ok(self.alice, "whoami", cwd=self.alice)
        # And the fix printed is the fix.
        self.join(self.alice)
        self.dispatch(self.alice)

    def test_an_unregistered_person_is_sent_to_join(self):
        self.join(self.alice)
        git(self.alice, "config", "user.name", "Carol Clark")
        err = self.refused(self.alice, "note", "--headline", "h", "--body", "b",
                           "--actor", "carol")
        self.assertIn("run.py join", err)


class TestNamespacedIds(FederationCase):

    def test_two_clones_allocate_in_their_own_namespaces(self):
        self.join(self.alice)
        self.join(self.bob)
        a = self.work(self.alice, proposed=["The bound is 9."])
        b = self.work(self.bob, proposed=["The other bound is 11."])
        self.assertEqual((a, b), ("R-alice-001", "R-bob-001"))
        self.assertEqual(json.loads((self.problem(self.alice) / "runs" / a /
                                     "ingest.json").read_text())["claims"],
                         ["C-alice-001"])
        self.assertEqual(json.loads((self.problem(self.bob) / "runs" / b /
                                     "ingest.json").read_text())["claims"],
                         ["C-bob-001"])
        self.assertTrue((self.problem(self.alice) / "claims" /
                         "ledger-alice.jsonl").exists())
        self.assertTrue((self.problem(self.alice) / "claims" / "_ids" /
                         "C-alice-001").exists())
        self.assertIn("C-alice-001",
                      (self.problem(self.alice) / "CLAIMS.md").read_text())
        self.assertEqual(self.dispatch_json(self.alice, a)["investigator"],
                         "alice")
        self.assertIn("host", self.dispatch_json(self.alice, a))

    def test_legacy_ids_still_parse_ingest_and_are_closable_by_anyone(self):
        legacy = self.work(self.bob, name="b0.md")            # before joining
        self.assertEqual(legacy, "R-001")
        old_claim = self.claims_ok(self.bob, "new", "--statement",
                                   "The founding claim.", "--actor", "director")
        self.assertIn("C-001", old_claim.stdout)
        self.join(self.bob)
        rid, _ = self.dispatch(self.bob, name="b1.md")
        self.assertEqual(rid, "R-bob-001")
        # The founding stream is still read, and a founding run is closable.
        old, _ = self.dispatch(self.bob, name="b2.md")
        (self.problem(self.bob) / "runs" / old).rename(
            self.problem(self.bob) / "runs" / "R-002")
        d = json.loads((self.problem(self.bob) / "runs" / "R-002" /
                        "dispatch.json").read_text())
        d.update(run="R-002", investigator=None)
        (self.problem(self.bob) / "runs" / "R-002" /
         "dispatch.json").write_text(json.dumps(d))
        r = self.ok(self.bob, "void", "R-002", "--reason", "superseded")
        self.assertIn("founding stream", r.stdout)
        self.assertIn("C-001",
                      (self.problem(self.bob) / "CLAIMS.md").read_text())


class TestOwnership(FederationCase):

    def foreign_run(self, clone, rid="R-alice-001"):
        d = self.problem(clone) / "runs" / rid
        d.mkdir(parents=True)
        (d / "dispatch.json").write_text(json.dumps(
            {"run": rid, "ts": "2026-01-01T00:00:00Z", "status": "open",
             "actor": "worker-a", "model": "worker-a", "investigator": "alice",
             "claims_pasted": [], "allowed": [], "timeout": 60}))
        return d

    def test_another_investigators_run_is_not_closed_by_you(self):
        self.join(self.bob)
        self.foreign_run(self.bob)
        for args in (("ingest", "R-alice-001"),
                     ("ingest", "R-alice-001", "--record-broken",
                      "--reason", "x"),
                     ("void", "R-alice-001", "--reason", "x")):
            err = self.refused(self.bob, *args)
            self.assertIn("belongs to alice", err)

    def test_the_guard_refuses_staging_another_investigators_run(self):
        self.join(self.bob)
        self.dispatch(self.bob)                      # installs the hook
        d = self.foreign_run(self.bob, "R-alice-002")
        (d / "note.txt").write_text("editing someone else's evidence\n")
        git(self.bob, "add", "problems/demo/runs/R-alice-002")
        r = git(self.bob, "commit", "-q", "-m", "tidy", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("R-alice-002", r.stderr)
        self.assertIn("another investigator", r.stderr)

    def test_a_duplicate_names_a_run_that_exists_and_is_listed_while_open(self):
        self.join(self.alice)
        self.join(self.bob)
        rid, _ = self.dispatch(self.alice)
        git(self.alice, "push", "-q", "origin", "lab/alice")
        git(self.bob, "fetch", "-q", "origin")
        err = self.refused(self.bob, "new", "--brief", str(self.brief(self.bob)),
                           "--no-launch", "--role", "manual",
                           "--duplicates", "R-alice-404")
        self.assertIn("no branch this clone can see", err)
        mine, r = self.dispatch(self.bob, extra=["--duplicates", rid])
        self.assertIn("deliberate duplicate of %s" % rid, r.stdout)
        self.assertEqual(self.dispatch_json(self.bob, mine)["duplicates"], rid)
        out = self.ok(self.bob, "catchup", "2020-01-01").stdout
        self.assertIn("%s duplicates %s" % (mine, rid), out)


class TestStreams(FederationCase):

    def test_status_is_the_latest_event_across_streams_and_rebuild_shows_it(self):
        self.join(self.alice)
        cid = self.claims_ok(self.alice, "new", "--statement", "A holds.",
                             "--actor", "director").stdout.splitlines()[0].strip()
        self.assertEqual(cid, "C-alice-001")
        # A second stream, as a merge from another branch would leave it.
        other = self.problem(self.alice) / "claims" / "ledger-bob.jsonl"
        other.write_text(json.dumps(
            {"event": "set", "id": cid, "ts": "2999-01-01T00:00:00Z",
             "actor": "bob", "from": "proposed", "to": "refuted",
             "evidence": None, "by": None, "statement": "A holds.",
             "conditions": "", "hash": "x"}, sort_keys=True) + "\n")
        r = self.ok(self.alice, "rebuild")
        self.assertIn("Rebuilt", r.stdout)
        view = (self.problem(self.alice) / "claims" / (cid + ".md")).read_text()
        self.assertIn("**Status:** refuted", view)
        self.assertIn("refuted", (self.problem(self.alice) / "CLAIMS.md").read_text())
        self.assertEqual(git(self.alice, "status", "--porcelain").stdout.strip(), "")

    def test_catchup_reads_the_other_branch_and_counts_what_is_unpushed(self):
        self.join(self.alice)
        self.join(self.bob)
        rid = self.work(self.bob, headline="Bob counted them.",
                        proposed=["Bob's bound is 11."])
        git(self.alice, "fetch", "-q", "origin")
        out = self.ok(self.alice, "catchup", "2020-01-01").stdout
        self.assertIn("Other investigators", out)
        self.assertIn("bob (origin/lab/bob)", out)
        self.assertIn("%s PASS" % rid, out)
        self.assertIn("C-bob-001 stated as proposed", out)
        self.assertIn("yours: unpushed 0", out)
        # Work of your own that has not left the laptop is counted.
        self.dispatch(self.alice)
        self.assertIn("yours: unpushed 1",
                      self.ok(self.alice, "catchup", "2020-01-01").stdout)


class TestMeeting(FederationCase):

    def status(self, clone, text):
        (self.problem(clone) / "STATUS.md").write_text(text)
        git(clone, "add", "problems/demo/STATUS.md")
        git(clone, "commit", "-q", "-m", "status")
        git(clone, "push", "-q", "origin", self.branch(clone))

    def test_reconcile_merges_agrees_and_fast_forwards_every_branch(self):
        self.join(self.alice)
        self.join(self.bob)
        self.work(self.alice, headline="Alice counted them.",
                  proposed=["The largest cap in dimension 4 has 20 points."])
        self.work(self.bob, headline="Bob counted them too.",
                  proposed=["The largest cap in dimension 4 has 20 points."])
        self.status(self.alice, "# Status: demo\n\n## Bottom line\n\nAlice's "
                                "reading of it.\n")
        self.status(self.bob, "# Status: demo\n\n## Bottom line\n\nBob's "
                              "reading of it.\n")

        r = self.ok(self.alice, "reconcile", cwd=self.alice)
        self.assertEqual(self.branch(self.alice), "main")
        out = r.stdout
        self.assertIn("Agenda", out)
        self.assertIn("STATUS.md", out)
        self.assertIn("state the same thing in two streams", out)
        self.assertIn("superseded", out)
        agenda = self.alice / "notebook" / "meetings"
        self.assertEqual(len([p for p in agenda.iterdir()
                              if p.name.endswith("-agenda.md")]), 1)
        copy = self.problem(self.alice) / "STATUS.md.bob"
        self.assertTrue(copy.exists(), "no copy of the page both sides wrote")
        self.assertIn("Bob's reading", copy.read_text())
        self.assertIn("Alice's reading",
                      (self.problem(self.alice) / "STATUS.md").read_text())
        # Both records are on main now, whoever wrote them.
        text = (self.problem(self.alice) / "CLAIMS.md").read_text()
        self.assertIn("C-alice-001", text)
        self.assertIn("C-bob-001", text)
        self.assertTrue((self.problem(self.alice) / "runs" / "R-bob-001").is_dir())

        err = self.refused(self.alice, "reconcile", "--close",
                           "--present", "alice,bob", cwd=self.alice)
        self.assertIn("STATUS.md.bob", err)

        # The room settles the page, then records the meeting.
        (self.problem(self.alice) / "STATUS.md").write_text(
            "# Status: demo\n\n## Bottom line\n\nWhat the room agreed.\n")
        copy.unlink()
        self.claims_ok(self.alice, "set", "C-bob-001", "superseded",
                       "--by", "C-alice-001", "--actor", "meeting today (alice,bob)",
                       "--problem", str(self.problem(self.alice)))
        r = self.ok(self.alice, "reconcile", "--close", "--present", "alice,bob",
                    cwd=self.alice)
        self.assertIn("closed and filed", r.stdout)
        log = git(self.alice, "log", "main", "--pretty=%s").stdout
        self.assertIn("meeting:", log)
        self.assertIn("(alice,bob)", log)
        note = [p for p in (self.alice / "notebook" / "meetings").iterdir()
                if not p.name.endswith("-agenda.md")]
        self.assertEqual(len(note), 1)
        filed = note[0].read_text()
        self.assertIn("**Present:** Alice (alice), Bob (bob)", filed)
        self.assertIn("C-bob-001", filed)
        # Every branch now starts from main, here and on the remote.
        head = git(self.alice, "rev-parse", "main").stdout.strip()
        for ref in ("lab/alice", "origin/main", "origin/lab/alice",
                    "origin/lab/bob"):
            self.assertEqual(git(self.alice, "rev-parse", ref).stdout.strip(),
                             head, "%s is not at main" % ref)
        # And bob's own clone fast-forwards onto it with no merge of his own.
        git(self.bob, "fetch", "-q", "origin")
        git(self.bob, "merge", "-q", "--ff-only", "origin/lab/bob")
        self.assertEqual(git(self.bob, "rev-parse", "HEAD").stdout.strip(), head)
        self.assertEqual(self.branch(self.alice), "lab/alice")
        self.assertEqual(git(self.alice, "status", "--porcelain").stdout.strip(), "")

    def test_a_claim_two_streams_disagree_on_runs_through_the_meeting(self):
        """The whole path: two streams leave one claim in two states, the
        agenda says so in words the room can act on, the decision is
        recorded, and the minutes file it under the item it settles."""
        self.join(self.alice)
        self.join(self.bob)
        self.work(self.alice, headline="Alice found it.",
                  proposed=["The bound in dimension 4 is 20."])
        git(self.bob, "fetch", "-q", "origin")
        # Bob reads Alice's claim stream onto his branch, as the meeting
        # would have left it after any earlier one.
        git(self.bob, "checkout", "origin/lab/alice", "--",
            "problems/demo/claims/ledger-alice.jsonl")
        git(self.bob, "commit", "-q", "-m", "read alice's claim stream")
        self.claims_ok(self.bob, "set", "C-alice-001", "refuted",
                       "--reason", "a counterexample at n = 12",
                       "--problem", "demo")
        git(self.bob, "push", "-q", "origin", "lab/bob")
        self.claims_ok(self.alice, "affirm", "C-alice-001",
                       "--reason", "the counterexample misreads the bound",
                       "--problem", "demo")
        git(self.alice, "push", "-q", "origin", "lab/alice")

        r = self.ok(self.alice, "reconcile", cwd=self.alice)
        out = r.stdout
        # The folded status is what the views show; the sentence also says
        # whose event was the last word, whoever that turns out to be.
        self.assertIn("C-alice-001 is currently refuted", out)
        self.assertIn("Bob (bob) has it refuted", out)
        self.assertIn("Alice (alice) has it proposed", out)
        self.assertIn("a counterexample at n = 12", out)     # each side's reason
        self.assertIn("the counterexample misreads the bound", out)
        self.assertIn("is the latest", out)
        # The command is ready to run: real date, real tags, the problem's slug.
        self.assertIn('--actor "meeting %s (alice,bob)"' % self.today(), out)
        self.assertIn("--problem demo", out)
        self.assertNotIn("<date>", out)
        self.assertNotIn("<tags>", out)

        # The room decides, and rewrites the page out of what it decided.
        # The folded status is already refuted, so the room's decision is to
        # keep it there — which is a decision, and goes on the ledger.
        self.claims_ok(self.alice, "affirm", "C-alice-001",
                       "--reason", "the room accepted the counterexample",
                       "--actor", "meeting %s (alice,bob)" % self.today(),
                       "--problem", "demo")
        (self.problem(self.alice) / "STATUS.md").write_text(
            "# Status: demo\n\n## Bottom line\n\nThe bound is open again.\n")
        git(self.alice, "add", "problems/demo/STATUS.md")
        git(self.alice, "commit", "-q", "-m", "status: the bound is open again")
        self.ok(self.alice, "reconcile", "--close", "--present", "alice,bob",
                cwd=self.alice)
        filed = [p for p in (self.alice / "notebook" / "meetings").iterdir()
                 if not p.name.endswith("-agenda.md")][0].read_text()
        self.assertIn("## Decisions", filed)
        self.assertIn("C-alice-001 affirmed as refuted", filed)
        self.assertIn("the room accepted the counterexample", filed)
        self.assertIn("STATUS.md rewritten (status: the bound is open again)",
                      filed)
        # Filed under the item it settles, not in a heap at the end.
        first = filed.split("## Decisions")[1]
        self.assertIn("**1.", first)

        # And afterwards nobody's branch reads as new work.
        git(self.alice, "fetch", "-q", "origin")
        others = self.ok(self.alice, "catchup").stdout.split(
            "Other investigators")[1]
        self.assertIn("nothing since the last meeting", others)

    def test_a_clone_catches_its_branch_up_after_the_meeting(self):
        self.join(self.alice)
        self.join(self.bob)
        self.work(self.bob, headline="Bob's run.")
        self.ok(self.alice, "reconcile", cwd=self.alice)
        self.ok(self.alice, "reconcile", "--close", "--present", "alice,bob",
                cwd=self.alice)
        out = self.ok(self.bob, "catchup").stdout
        self.assertIn("the meeting moved it", out)
        self.assertIn("fast-forwarded", out)
        self.assertEqual(git(self.bob, "rev-parse", "HEAD").stdout.strip(),
                         git(self.alice, "rev-parse", "main").stdout.strip())

    def today(self):
        import datetime
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    def test_catchup_defaults_to_the_last_meeting(self):
        self.join(self.alice)
        self.work(self.alice, headline="Before the meeting.")
        self.ok(self.alice, "reconcile", cwd=self.alice)
        self.ok(self.alice, "reconcile", "--close", "--present", "alice",
                cwd=self.alice)
        out = self.ok(self.alice, "catchup").stdout
        self.assertIn("Since the last meeting", out)

    def test_one_investigator_reconciles_to_an_empty_agenda(self):
        self.join(self.alice)
        self.work(self.alice, headline="Alone but recorded.")
        r = self.ok(self.alice, "reconcile", cwd=self.alice)
        self.assertIn("Nothing to settle", r.stdout)
        r = self.ok(self.alice, "reconcile", "--close", "--present", "alice",
                    cwd=self.alice)
        self.assertIn("closed and filed", r.stdout)
        self.assertEqual(self.branch(self.alice), "lab/alice")
        self.assertEqual(git(self.alice, "rev-parse", "lab/alice").stdout,
                         git(self.alice, "rev-parse", "main").stdout)
        self.assertIn("meeting:", git(self.alice, "log", "--pretty=%s").stdout)

    def test_reconcile_refuses_a_dirty_tree_and_pushes_for_you(self):
        """The keyboard-holder is the only writer of their own branch, so
        the meeting pushes it rather than sending them away to do it."""
        self.join(self.alice)
        (self.problem(self.alice) / "STATUS.md").write_text("# half a thought\n")
        err = self.refused(self.alice, "reconcile", cwd=self.alice)
        self.assertIn("uncommitted", err)
        git(self.alice, "add", "problems/demo/STATUS.md")
        git(self.alice, "commit", "-q", "-m", "status")
        ahead = git(self.alice, "rev-list", "--count",
                    "origin/lab/alice..lab/alice").stdout.strip()
        self.assertEqual(ahead, "1")
        self.ok(self.alice, "reconcile", cwd=self.alice)
        self.assertEqual(git(self.alice, "rev-parse", "origin/lab/alice").stdout,
                         git(self.alice, "rev-parse", "lab/alice").stdout)


if __name__ == "__main__":
    unittest.main()
