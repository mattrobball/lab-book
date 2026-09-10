"""Smoke tests for what run.py actually does today. Each test names the
behaviour it pins; the expectedFailure ones pin a defect from
HARNESS_ISSUES.md and start passing when that entry is fixed."""
import json
import tempfile
import unittest
from pathlib import Path

import run


def make_run(problem, rid, result, ret):
    packet = problem / "runs" / rid / "packet"
    packet.mkdir(parents=True)
    (packet / "RESULT.md").write_text(result)
    (packet / "RETURN.json").write_text(json.dumps(ret))


GOOD_RESULT = """# VERDICT: PASS
One sentence.

## What was done

Ran it.

## Not claimed

Nothing beyond the run.

## Leads

None.

## Validation

    python3 packet/check.py
    prints CHECK_OK
"""

GOOD_RET = {"headline": "It works.", "exits": ["done"], "validation": "replay",
            "machine_markers": ["CHECK_OK"], "claims_used": ["C-001"],
            "claims_proposed": ["The ring has three generators."]}


class ReplayCommandTests(unittest.TestCase):
    def test_indented_block_is_taken_whole(self):
        text = "Run:\n\n    python3 check.py\n    grep OK out.txt\n\nThen stop."
        self.assertEqual(run.replay_command(text),
                         "python3 check.py\ngrep OK out.txt")

    def test_no_block_means_no_command(self):
        self.assertIsNone(run.replay_command("Nothing to run here."))

    @unittest.expectedFailure
    def test_fenced_expected_output_is_not_run_as_the_command(self):
        # HARNESS_ISSUES.md #8: a fenced block of expected output placed
        # after the indented command is picked instead of the command.
        text = ("    python3 check.py\n\nExpected:\n\n```\nCHECK_OK\n```\n")
        self.assertEqual(run.replay_command(text), "python3 check.py")


class FenceTests(unittest.TestCase):
    def test_outside_reports_paths_not_under_an_allowed_prefix(self):
        allowed = ["problems/p/runs/R-001/"]
        changed = {"problems/p/runs/R-001/packet/RESULT.md",
                   "problems/p/STATUS.md", "briefs/x.md"}
        self.assertEqual(run.outside(changed, allowed),
                         ["briefs/x.md", "problems/p/STATUS.md"])


class DuplicateWarningTests(unittest.TestCase):
    def test_similar_statements_are_flagged_and_different_ones_are_not(self):
        a = "Every affine Dynkin quiver of type E6 has Orlov spectrum {1,2}."
        b = "Every affine Dynkin quiver of type E6 has Orlov spectrum {1, 2}."
        c = "The free ring on two generators has ultimate dimension four."
        self.assertTrue(run.similar(a, b))
        self.assertFalse(run.similar(a, c))


class PacketGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.problem = Path(self.tmp.name)
        self.dispatch = {"claims_pasted": ["C-001"]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_good_packet_passes(self):
        make_run(self.problem, "R-001", GOOD_RESULT, GOOD_RET)
        verdict, secs, ret = run.read_packet(self.problem, "R-001", self.dispatch)
        self.assertEqual(verdict, "PASS")
        self.assertIn("python3 packet/check.py", secs["validation"])

    def test_pending_result_is_refused(self):
        make_run(self.problem, "R-002",
                 GOOD_RESULT.replace("# VERDICT: PASS", "# VERDICT: PENDING"),
                 GOOD_RET)
        with self.assertRaises(SystemExit):
            run.read_packet(self.problem, "R-002", self.dispatch)

    def test_claim_id_inside_claims_proposed_is_refused(self):
        ret = dict(GOOD_RET, claims_proposed=["C-488: this is a restatement"])
        make_run(self.problem, "R-003", GOOD_RESULT, ret)
        with self.assertRaises(SystemExit):
            run.read_packet(self.problem, "R-003", self.dispatch)

    def test_claims_used_must_be_pasted_by_the_brief(self):
        ret = dict(GOOD_RET, claims_used=["C-615"])
        make_run(self.problem, "R-004", GOOD_RESULT, ret)
        with self.assertRaises(SystemExit):
            run.read_packet(self.problem, "R-004", self.dispatch)

    def test_reviewed_list_is_recorded_on_the_target(self):
        make_run(self.problem, "R-005", GOOD_RESULT, GOOD_RET)
        target = self.problem / "runs" / "R-005" / "ingest.json"
        target.write_text(json.dumps({"run": "R-005", "actor": "model-a"}))
        notes, touched = run.apply_reviews(
            self.problem, "R-006", {"reviewed": ["R-005"]}, "PASS", "model-b")
        self.assertEqual(touched, ["R-005"])
        self.assertEqual(json.loads(target.read_text())["reviewed_by"], ["R-006"])

    def test_same_actor_review_is_refused(self):
        make_run(self.problem, "R-007", GOOD_RESULT, GOOD_RET)
        (self.problem / "runs" / "R-007" / "ingest.json").write_text(
            json.dumps({"run": "R-007", "actor": "model-a"}))
        with self.assertRaises(SystemExit):
            run.apply_reviews(self.problem, "R-008", {"reviewed": ["R-007"]},
                              "PASS", "Model-A")

    @unittest.expectedFailure
    def test_reviewed_as_a_bare_string_is_accepted(self):
        # HARNESS_ISSUES.md 2026-09-03: a string is iterated character by
        # character and refused with a confusing message.
        make_run(self.problem, "R-009", GOOD_RESULT, GOOD_RET)
        (self.problem / "runs" / "R-009" / "ingest.json").write_text(
            json.dumps({"run": "R-009", "actor": "model-a"}))
        notes, touched = run.apply_reviews(
            self.problem, "R-010", {"reviewed": "R-009"}, "PASS", "model-b")
        self.assertEqual(touched, ["R-009"])

    def test_already_ingested_run_is_refused(self):
        # R-038 was ingested twice on 2026-09-02. load_dispatch refuses any
        # run whose dispatch.json is no longer "open".
        rundir = self.problem / "runs" / "R-011"
        rundir.mkdir(parents=True)
        (rundir / "dispatch.json").write_text(json.dumps(
            {"run": "R-011", "status": "ingested", "verdict": "PASS",
             "ingested_at": "2026-09-02T19:44:32Z"}))
        with self.assertRaises(SystemExit):
            run.load_dispatch(self.problem, "R-011")

    def test_open_run_loads(self):
        rundir = self.problem / "runs" / "R-012"
        rundir.mkdir(parents=True)
        (rundir / "dispatch.json").write_text(json.dumps(
            {"run": "R-012", "status": "open", "claims_pasted": []}))
        self.assertEqual(run.load_dispatch(self.problem, "R-012")["run"], "R-012")


if __name__ == "__main__":
    unittest.main()
