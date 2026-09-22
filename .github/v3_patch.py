"""One-use, exact-base integration patch. Removed from the completed tree."""
import hashlib
from pathlib import Path

BASE = {
 'skills/open-lab/scripts/claims.py': '27eb4157ef6d19f5bf896bf9c2197c2e4dca7373',
 'skills/open-lab/scripts/run.py': 'dae6dfc68b51376ff9a4308c5f827d56253f22fa',
 'skills/open-lab/scripts/tests/test_run.py': 'fc6a10527b93b83423190a8f8ad74e890a439c73',
 'skills/open-lab/scripts/tests/test_federation.py': '3a71c1763f21b6e6c72248852856b17345957e62',
}

def blob(data):
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()


def replace(text, old, new):
    assert text.count(old) == 1, repr(old[:100])
    return text.replace(old, new, 1)


for name, sha in BASE.items():
    assert blob(Path(name).read_bytes()) == sha, 'base drift: '+name

p = Path('skills/open-lab/scripts/claims.py')
s = p.read_text()
s = replace(s, 'from pathlib import Path\n', 'from pathlib import Path\n\n# Keep sibling-module callbacks on the same committed-record cache as the CLI.\nif __name__ == "__main__":\n    sys.modules["claims"] = sys.modules[__name__]\n')
s = replace(s, 'import socket\n', 'import socket\nimport rectification\n')
s = replace(s, '    return fold(events)\n', '    known, order = fold(events)\n    rectification.attach(problem, known, include_remote)\n    return known, order\n')
s = replace(s, '    lines += ["", "## Statement",', '    for notice in rectification.summary({c["id"]: c}):\n        lines.append("**Comparison:** " + notice)\n    lines += ["", "## Statement",')
s = replace(s, '    return "\\n".join(lines) + "\\n"\n\n\ndef one_line', '    for rec in c["history"]:\n        if rec.get("acknowledged_contradictions"):\n            lines.append("- Promotion over explicitly acknowledged open contradictions: "\n                         + json.dumps(rec["acknowledged_contradictions"], sort_keys=True))\n    return "\\n".join(lines) + "\\n"\n\n\ndef one_line')
s = replace(s, '    (problem / "CLAIMS.md").write_text("\\n".join(rows) + "\\n")', '    notices = rectification.summary(claims)\n    if notices:\n        rows += ["", "## Comparison notices", ""] + ["- " + n for n in notices]\n    (problem / "CLAIMS.md").write_text("\\n".join(rows) + "\\n")')
s = replace(s, '    regenerate(problem)\n    commit(problem, "%s new (%s)"', '    rectification.check_new(problem, [cid], tag)\n    regenerate(problem)\n    commit(problem, "%s new (%s)"')
s = replace(s, '    rec = {"event": "set", "id": cid, "ts": now(), "actor": actor,\n           "from": old,', '''    acknowledged = []
    if target == "verified":
        visible, _ = load(problem, include_remote=True)
        conflicts = visible[cid].get("contradictions", [])
        required = {n["key"] for n in conflicts}
        supplied = set(getattr(args, "acknowledge_contradictions", None) or [])
        for notice in conflicts:
            print("Open contradiction: %s / %s [%s], pair %s"
                  % (cid, notice["other"], notice["source"], notice["key"]))
        if required != supplied:
            refuse("acknowledge each CURRENT open contradiction explicitly with "
                   "--acknowledge-contradictions <pair hash>; no status changed. "
                   "Required: %s" % (", ".join(sorted(required)) or "none"))
        acknowledged = conflicts
    rec = {"event": "set", "id": cid, "ts": now(), "actor": actor,
           "from": old,''')
s = replace(s, '        rec["independence"] = independence\n', '        rec["independence"] = independence\n        rec["acknowledged_contradictions"] = acknowledged\n')
s = replace(s, '    if warnings:\n        print("%d thing(s) to look at:"', '    warnings += rectification.summary(claims)\n    if warnings:\n        print("%d thing(s) to look at:"')
s = replace(s, '    s.set_defaults(func=cmd_set)', '    s.add_argument("--acknowledge-contradictions", action="append", metavar="PAIR_HASH",\n                   help="explicitly acknowledge this current open pair when verifying; repeat for each")\n    s.set_defaults(func=cmd_set)')
s = replace(s, '    for q in (n, s, c, b, a):', '''    x = sub.add_parser("compare", help="compare named claim versions; no status changes")
    x.add_argument("--new", action="append", required=True, metavar="CLAIM_ID")
    x.add_argument("--mock-responses", help="explicit MOCK probability fixtures, never live judgments")
    x.set_defaults(func=rectification.cmd_compare)
    d = sub.add_parser("dismiss", help="record a human dismissal of a current comparison flag")
    d.add_argument("pair")
    d.add_argument("--kind", choices=("contradiction", "duplicate", "adjudication"), required=True)
    d.add_argument("--reason", required=True)
    d.add_argument("--issue", help="issue URL or meeting reference for this ruling")
    d.set_defaults(func=rectification.cmd_dismiss)

    for q in (n, s, c, b, a, x, d):''')
s = replace(s, '    for q in (n, s, a):', '    for q in (n, s, a, d):')
p.write_text(s)

p = Path('skills/open-lab/scripts/run.py')
s = p.read_text()
s = replace(s, 'import claims                                    # noqa:', 'import rectification\nimport reservations\nimport claims                                    # noqa:')
s = replace(s, '    write_json(rundir / "dispatch.json", dispatch)\n', '    reservations.preregister(root, problem, dispatch, body)\n    write_json(rundir / "dispatch.json", dispatch)\n')
s = replace(s, '    print("%s — model %s, timeout %ss, may write: %s"', '    print("%s — model %s, timeout %ss, may write: %s"')
# Preserve the first stdout token: callers parse the allocated ID there.
s = replace(s, '    if duplicate_of:\n', '    for notice in reservations.notices(dispatch):\n        print(notice)\n    if duplicate_of:\n')
s = replace(s, '        dupes = near_duplicates(problem, statement)\n', '')
s = replace(s, '''        if dupes:
            warnings.append("%s looks close to %s already on file — read them "
                            "side by side before either is promoted"
                            % (cid, ", ".join(dupes)))
''', '''    comparison = rectification.check_new(problem, [cid for cid, _ in allocated], tag) if allocated else None
    if comparison and (comparison["deferred"] or comparison["source"] == "mock"):
        warnings.append("Comparison coverage: " + json.dumps(comparison, sort_keys=True))
''')
s = replace(s, '    write_json(rundir / "ingest.json", record)\n', '    record["comparison"] = comparison\n    record["lease"] = d.get("lease")\n    record["reservation_outcome"] = reservations.release(root, d)\n    write_json(rundir / "ingest.json", record)\n')
s = replace(s, '                    "validation": None,\n', '                    "validation": None,\n                    "lease": d.get("lease"),\n                    "reservation_outcome": reservations.release(root, d),\n')
s = replace(s, '    d.update(status="void", verdict="VOID", ingested_at=now(),\n', '    d["reservation_outcome"] = reservations.release(root, d)\n    d.update(status="void", verdict="VOID", ingested_at=now(),\n')
s = replace(s, '    status_report(problem)\n    baseline_report(problem, root)\n', '''    visible, _ = claims.load(problem, include_remote=True)
    for notice in rectification.summary(visible):
        print("- " + notice)
    flight = reservations.rpc(root, "list_leases", {"problem": str(problem.relative_to(root))})
    print("\nReservations: " + (json.dumps(flight["reservations"], sort_keys=True)
          if flight.get("available") else "unavailable; not evidence that nobody is working"))
    status_report(problem)
    baseline_report(problem, root)
''')
s = replace(s, '                if not similar(known[a]["statement"], known[b]["statement"]):', '                if b not in {n["other"] for n in known[a].get("duplicate-candidate-of", [])}:')
s = replace(s, '                    "%s and %s state the same thing in two streams. The room "', '                    "%s and %s are duplicate candidates in two streams. The room "')
s = replace(s, 'KIT_FILES = (("run.py", "scripts/run.py"), ("claims.py", "scripts/claims.py"),', '''KIT_FILES = (("run.py", "scripts/run.py"), ("claims.py", "scripts/claims.py"),
             ("rectification.py", "scripts/rectification.py"),
             ("reservations.py", "scripts/reservations.py"),
             ("board.py", "scripts/board.py"),
             ("v3", "assets/v3"),''')
s = replace(s, '    if name.startswith("ledger") and name.endswith(".jsonl"):', '    if name.startswith(("ledger", "rectification")) and name.endswith(".jsonl"):')
# Older test kits may not contain v3 files: commit only files actually copied.
s = replace(s, '    paths = [name for name, _ in KIT_FILES] + ["lab.json"]', '    paths = [name for name, _ in KIT_FILES if (root / name).exists()] + ["lab.json"]')
p.write_text(s)
# Record the origin of dependency demotions for the board's affected cone.
p = Path('skills/open-lab/scripts/claims.py')
s = p.read_text()
s = replace(s, 'events.append({"event": "set", "id": other, "ts": when, "actor": actor,',
               'events.append({"event": "set", "id": other, "ts": when, "actor": actor, "cascade_from": cid,')
p.write_text(s)

p = Path('skills/open-lab/scripts/tests/test_run.py')
s = p.read_text()
s = replace(s, '    def test_near_duplicate_claim_warns(self):', '    def test_unavailable_comparison_is_deferred_not_word_overlap(self):')
s = replace(s, '        self.assertIn("looks close to C-001", r.stdout)',
               '        self.assertNotIn("looks close to C-001", r.stdout)\n        self.assertIn("deferred", r.stdout)')
p.write_text(s)

p = Path('skills/open-lab/scripts/tests/test_federation.py')
s = p.read_text()
s = replace(s, '        self.assertIn("state the same thing in two streams", out)',
               '        self.assertNotIn("state the same thing in two streams", out)\n        self.assertIn("comparison deferred", (self.problem(self.alice) / "CLAIMS.md").read_text())')
s = replace(s, '        self.assertIn("superseded", out)\n', '')
p.write_text(s)
print('Integrated v3 from the inspected base; old heuristic assertions now require honest deferred coverage.')

# Integrate the already-pushed new module's last reviewed cache correction.
p = Path('skills/open-lab/scripts/rectification.py')
s = p.read_text()
s = replace(s, "if source == 'unavailable' or cache[key]['source'] == source:",
            "if cache[key]['source'] == source:")
p.write_text(s)

p = Path('skills/open-lab/SKILL.md')
s = replace(p.read_text(), 'version: "2.1.0"', 'version: "3.0.0-alpha.1"')
s = replace(s, '   - `scripts/run.py` → `run.py`', '   - `scripts/run.py` → `run.py`\n   - `scripts/rectification.py`, `scripts/reservations.py`, `scripts/board.py` → the same names in the lab root\n   - `assets/v3/` → `v3/` (optional host setup and lab CI instructions)')
p.write_text(s)
for name in ('.claude-plugin/plugin.json', '.claude-plugin/marketplace.json'):
    p = Path(name)
    p.write_text(replace(p.read_text(), '"version": "2.1.0"', '"version": "3.0.0-alpha.1"'))

p = Path('DESIGN_V3.md')
s = p.read_text()
s = replace(s, 'Status: design, not built.', 'Status: minimal first pass on the implementation branch; see `V3_IMPLEMENTATION.md` for implemented scope and verification.')
s = replace(s, 'The board writes reservations — take, release, preempt — and marks a pair adjudicated.', 'The board writes notices — take and release the caller\'s own — and hands adjudication to issues and the claim CLI in this first pass. There is no preemption (Investigator correction, 2026-09-22).')
p.write_text(s)
p = Path('DESIGN_QUEUE.md')
p.write_text(p.read_text() + '\n\n### Implementation clarification (Investigator, 2026-09-22)\n\nMinimal first pass authorized. There is **no preemption**: coordination only\nannounces existing work. This supersedes the preempt wording in decision 2.\nJev calls are mocked for behavior tests; no paid API calls are made.\nImplementation and evidence are described in `V3_IMPLEMENTATION.md`.\n')
p = Path('README.md')
p.write_text(replace(p.read_text(), '# Lab Book\n', '# Lab Book\n\n**v3 first pass (3.0.0-alpha.1):** advisory claim comparisons, notice-only\nreservations, and a private static board. See `V3_IMPLEMENTATION.md` and\n`skills/open-lab/assets/v3/README.md`. Jev behavior is mocked, not a live paid\nservice. Nothing has been deployed to a lab host. The existing lab workflow\nand evidence rules below remain in force.\n'))
