"""A step down cascades: verified claims standing on a demoted claim go to
conditional; a supersession by a verified claim repoints them instead."""
import unittest

import claims


def ev_new(cid, rests, ts):
    return {"event": "new", "id": cid, "ts": ts, "actor": "a",
            "status": "proposed", "statement": "S " + cid, "conditions": "",
            "rests_on": rests, "hash": "h"}


def ev_set(cid, to, ts, by=None):
    return {"event": "set", "id": cid, "ts": ts, "actor": "b", "to": to,
            "hash": "h", "by": by, "evidence": "R-001"}


def ledger(*events):
    return claims.fold([(e, "") for e in events])[0]


class CascadeTests(unittest.TestCase):
    def chain(self):
        # C-001 <- C-002 <- C-003 (all verified), C-004 conditional on C-001
        return ledger(
            ev_new("C-001", [], "2026-09-01T00:00:00Z"), ev_new("C-002", ["C-001"], "2026-09-01T00:00:00Z"),
            ev_new("C-003", ["C-002"], "2026-09-01T00:00:00Z"), ev_new("C-004", ["C-001"], "2026-09-01T00:00:00Z"),
            ev_new("C-005", [], "2026-09-01T00:00:00Z"),
            ev_set("C-001", "verified", "2026-09-02T00:00:00Z"), ev_set("C-002", "verified", "2026-09-03T00:00:00Z"),
            ev_set("C-003", "verified", "2026-09-04T00:00:00Z"), ev_set("C-005", "verified", "2026-09-04T00:00:00Z"),
            ev_set("C-004", "conditional", "2026-09-05T00:00:00Z"))

    def test_demotion_reaches_every_verified_dependent(self):
        plan = claims.cascade_plan(self.chain(), "C-001", "conditional", None,
                                   "mrb", "2026-09-10T00:00:00Z")
        self.assertEqual([(e["id"], e["to"]) for e in plan],
                         [("C-002", "conditional"), ("C-003", "conditional")])
        self.assertIn("C-001 is verified again", plan[0]["conditions"])
        # and the plan folds into the ledger it came from
        events = [(e, "") for e in plan]
        known = claims.fold([(ev_new("C-001", [], "2026-09-01T00:00:00Z"), ""),
                             (ev_new("C-002", ["C-001"], "2026-09-01T00:00:00Z"), ""),
                             (ev_set("C-002", "verified", "2026-09-03T00:00:00Z"), "")] + events[:1])[0]
        self.assertEqual(known["C-002"]["status"], "conditional")

    def test_supersession_by_a_verified_claim_repoints_instead(self):
        plan = claims.cascade_plan(self.chain(), "C-001", "superseded", "C-005",
                                   "mrb", "2026-09-10T00:00:00Z")
        self.assertEqual([(e["event"], e["id"], e["rests_on"]) for e in plan],
                         [("affirm", "C-002", ["C-005"]),
                          ("affirm", "C-004", ["C-005"])])
        known = claims.fold([(ev_new("C-002", ["C-001"], "2026-09-01T00:00:00Z"), ""),
                             (ev_set("C-002", "verified", "2026-09-03T00:00:00Z"), ""),
                             (plan[0], "")])[0]
        self.assertEqual(known["C-002"]["rests_on"], ["C-005"])
        self.assertEqual(known["C-002"]["status"], "verified")

    def test_supersession_by_an_unverified_claim_demotes(self):
        plan = claims.cascade_plan(self.chain(), "C-001", "superseded", "C-004",
                                   "mrb", "2026-09-10T00:00:00Z")
        self.assertEqual([e["id"] for e in plan], ["C-002", "C-003"])
        self.assertIn("C-004, which supersedes C-001, is verified",
                      plan[0]["conditions"])


if __name__ == "__main__":
    unittest.main()
