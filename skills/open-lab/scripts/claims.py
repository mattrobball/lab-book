#!/usr/bin/env python3
"""Claim ledger for one problem.

Per problem: claims/ledger.jsonl is the only truth, claims/_ids/ holds one
marker file per allocated ID, and C-NNN.md plus CLAIMS.md are views rebuilt
from the ledger. Every state change is committed, because git is the layer
that makes tampering visible.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

STATUSES = ["proposed", "conditional", "verified", "externally-established",
            "accepted-by-investigator", "refuted", "superseded"]
MOVES = {
    "proposed": {"conditional", "verified", "externally-established",
                 "accepted-by-investigator", "refuted", "superseded"},
    "conditional": {"verified", "proposed", "refuted", "superseded"},
    "externally-established": {"conditional", "proposed", "refuted", "superseded"},
    "accepted-by-investigator": {"proposed", "refuted", "superseded"},
    "verified": {"proposed", "refuted", "superseded"},
    "refuted": set(),
    "superseded": set(),
}
TERMINAL = {"refuted": "refuted", "superseded": "superseded"}
RUN_ID = re.compile(r"^R-\d+$")
CLAIM_ID = re.compile(r"^C-\d+$")
HEADING = re.compile(r"^## +(.+?)\s*$", re.M)
COMMENT = re.compile(r"<!--.*?-->", re.S)


LAST_REFUSAL = {"message": None}


def refuse(message):
    LAST_REFUSAL["message"] = message
    sys.stderr.write("Refused: " + message + "\n")
    raise SystemExit(2)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def text_hash(statement, conditions):
    body = statement.strip() + "\n--\n" + conditions.strip()
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- locating

def find_problem(explicit):
    if explicit:
        d = Path(explicit).resolve()
        if not d.is_dir():
            refuse("there is no directory at %s. Pass --problem with the path "
                   "of the problem you mean." % explicit)
        return d
    here = Path.cwd().resolve()
    for d in [here] + list(here.parents):
        if (d / "claims").is_dir() or d.parent.name == "problems":
            return d
        if (d / ".git").exists():          # never wander out of the lab
            break
    refuse("I cannot tell which problem you mean from this directory. Run this "
           "from inside a problem directory, or pass --problem with its path.")


def git_root(problem):
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(problem),
                       capture_output=True, text=True)
    if r.returncode != 0:
        refuse("%s is not inside a git repository, and git is what makes a "
               "changed ledger visible later. Run `git init` at the top of the "
               "lab and commit what is here, then try again." % problem)
    return Path(r.stdout.strip())


# ---------------------------------------------------------------- ledger

def ledger_path(problem):
    return problem / "claims" / "ledger.jsonl"


def load(problem):
    claims, order = {}, []
    path = ledger_path(problem)
    if not path.exists():
        return claims, order
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        cid = rec["id"]
        if rec["event"] == "new":
            claims[cid] = {"id": cid, "status": rec["status"],
                           "discoverer": rec["actor"], "statement": rec["statement"],
                           "conditions": rec["conditions"], "rests_on": rec["rests_on"],
                           "hash": rec["hash"], "evidence": None, "confirmed_by": None,
                           "independence": None,
                           "superseded_by": None, "history": [rec]}
            order.append(cid)
        else:
            c = claims[cid]
            c.update(status=rec["to"], hash=rec["hash"],
                     statement=rec.get("statement", c["statement"]),
                     conditions=rec.get("conditions", c["conditions"]))
            if rec["to"] == "proposed":            # a demotion drops its backing
                c["evidence"], c["confirmed_by"] = None, None
            if rec.get("evidence"):
                c["evidence"] = rec["evidence"]
            if rec["to"] in ("verified", "externally-established",
                             "accepted-by-investigator"):
                c["confirmed_by"] = rec["actor"]
            if rec.get("independence"):
                c["independence"] = rec["independence"]
            if rec.get("rests_on") is not None:
                c["rests_on"] = rec["rests_on"]
            c["superseded_by"] = rec.get("by") or c["superseded_by"]
            c["history"].append(rec)
    return claims, order


def append(problem, rec):
    path = ledger_path(problem)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    with os.fdopen(fd, "a") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


def allocate(problem, actor):
    """Take the next free C-NNN. O_EXCL means two allocators racing here can
    never walk away with the same ID: one creation wins, the loser moves on."""
    ids = problem / "claims" / "_ids"
    ids.mkdir(parents=True, exist_ok=True)
    taken = [int(p.name.split("-")[1]) for p in ids.iterdir() if CLAIM_ID.match(p.name)]
    claims, _ = load(problem)
    taken += [int(c.split("-")[1]) for c in claims]
    n = max(taken) if taken else 0
    while True:
        n += 1
        cid = "C-%03d" % n
        try:
            fd = os.open(str(ids / cid), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w") as fh:
            fh.write("%s %s\n" % (now(), actor))
        return cid


# ---------------------------------------------------------------- views

def sections(path):
    if not path.exists():
        return {}
    parts = HEADING.split(path.read_text())
    out = {}
    for i in range(1, len(parts) - 1, 2):
        out[parts[i].strip().lower()] = COMMENT.sub("", parts[i + 1]).strip()
    return out


def view_text(c):
    lines = ["# %s" % c["id"], "",
             "<!-- Generated by claims.py from claims/ledger.jsonl. Do not edit the",
             "     header by hand, and never change status here. -->", "",
             "**Status:** %s" % c["status"],
             "**Discovered by:** %s" % c["discoverer"],
             "**Confirmed by:** %s" % (c["confirmed_by"] or "—")]
    if c.get("independence"):
        lines.append("**Independence:** %s" % c["independence"])
    if c["superseded_by"]:
        lines.append("**Superseded by:** %s" % c["superseded_by"])
    lines += ["", "## Statement", "", c["statement"].strip(), "",
              "## Conditions", "", c["conditions"].strip() or "None stated.", "",
              "## Evidence", "", c["evidence"] or "None on record.", "",
              "## Rests on", "", ", ".join(c["rests_on"]) or "Nothing.", "",
              "## History", ""]
    for rec in c["history"]:
        if rec["event"] == "new":
            lines.append("- %s — stated as %s, by %s" % (rec["ts"], rec["status"], rec["actor"]))
        else:
            tail = " (%s)" % rec["evidence"] if rec.get("evidence") else ""
            tail += " replaced by %s" % rec["by"] if rec.get("by") else ""
            lines.append("- %s — %s -> %s, by %s%s"
                         % (rec["ts"], rec["from"], rec["to"], rec["actor"], tail))
    return "\n".join(lines) + "\n"


def one_line(s, width=88):
    s = " ".join(s.split()).replace("|", "\\|")
    return s if len(s) <= width else s[:width - 1] + "…"


def regenerate(problem):
    claims, order = load(problem)
    for cid in order:
        (problem / "claims" / (cid + ".md")).write_text(view_text(claims[cid]))
    rows = ["# Claims", "",
            "<!-- Generated by claims.py from claims/ledger.jsonl. Do not edit. -->", "",
            "| ID | Status | Statement | Discovered by | Evidence |",
            "|---|---|---|---|---|"]
    for cid in order:
        c = claims[cid]
        rows.append("| [%s](claims/%s.md) | %s | %s | %s | %s |"
                    % (cid, cid, c["status"], one_line(c["statement"]),
                       c["discoverer"], c["evidence"] or "—"))
    if not order:
        rows.append("| — | — | No claims yet. | — | — |")
    (problem / "CLAIMS.md").write_text("\n".join(rows) + "\n")


def commit(problem, message):
    root = git_root(problem)
    paths = [str((problem / "claims").relative_to(root)),
             str((problem / "CLAIMS.md").relative_to(root))]
    subprocess.run(["git", "add", "--"] + paths, cwd=str(root), check=True,
                   capture_output=True)
    r = subprocess.run(["git", "commit", "-m", message, "--"] + paths,
                       cwd=str(root), capture_output=True, text=True)
    if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr):
        refuse("git would not record this change:\n%s\nFix the repository "
               "(usually an unset user.name or user.email), then run the same "
               "command again." % (r.stdout + r.stderr).strip())


# ---------------------------------------------------------------- evidence

def run_model(problem, run_id):
    p = problem / "runs" / run_id / "dispatch.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text()).get("model")
    except (json.JSONDecodeError, OSError):
        return None


def provider(model):
    """Crude on purpose: the goal is 'same house or not', not taxonomy."""
    if not model:
        return None
    m = model.lower()
    for prefix, name in (("gpt", "openai"), ("codex", "openai"), ("o1", "openai"),
                         ("claude", "anthropic"), ("grok", "xai"),
                         ("gemini", "google")):
        if m.startswith(prefix):
            return name
    return m.split("/")[0] if "/" in m else m


def discovering_run(problem, cid):
    """The run whose ingest allocated this claim, if any run did."""
    runs = problem / "runs"
    if not runs.is_dir():
        return None
    for d in sorted(runs.iterdir()):
        rec = d / "ingest.json"
        if rec.exists():
            try:
                if cid in (json.loads(rec.read_text()).get("claims") or []):
                    return d.name
            except (json.JSONDecodeError, OSError):
                continue
    return None


def dependents(claims, cid):
    """Every claim resting on cid, transitively."""
    out, frontier = [], [cid]
    while frontier:
        target = frontier.pop()
        for other, c in claims.items():
            if target in (c.get("rests_on") or []) and other not in out:
                out.append(other)
                frontier.append(other)
    return sorted(out)


def run_on_record(problem, run_id):
    for cand in (problem / "runs" / run_id / "RETURN.json",
                 problem / "runs" / run_id / "packet" / "RETURN.json"):
        if cand.exists():
            return True
    return False


# ---------------------------------------------------------------- commands

def cmd_new(args):
    problem = find_problem(args.problem)
    git_root(problem)
    rests = []
    for chunk in args.rests_on or []:
        rests += [x.strip() for x in chunk.split(",") if x.strip()]
    for r in rests:
        if not CLAIM_ID.match(r):
            refuse("%s is not a claim ID. Rest a claim on IDs like C-004, one "
                   "per --rests-on or comma separated." % r)
    known, _ = load(problem)
    for r in rests:
        if r not in known:
            print("Warning: this claim rests on %s, which is not a claim here "
                  "yet. `claims.py check` will keep flagging it." % r)
    cid = allocate(problem, args.actor)
    append(problem, {"event": "new", "id": cid, "ts": now(), "actor": args.actor,
                     "status": "proposed", "statement": args.statement.strip(),
                     "conditions": (args.conditions or "").strip(), "rests_on": rests,
                     "hash": text_hash(args.statement, args.conditions or "")})
    regenerate(problem)
    commit(problem, "%s new (proposed)" % cid)
    print(cid)


def cmd_set(args):
    problem = find_problem(args.problem)
    git_root(problem)
    claims, _ = load(problem)
    cid, target = args.claim, args.status
    if target not in STATUSES:
        refuse("%s is not one of the statuses. Use one of: %s."
               % (target, ", ".join(STATUSES)))
    if cid not in claims:
        refuse("%s is not a claim in this ledger. Run `claims.py check` to see "
               "the claims on file, or allocate a new one with `claims.py new`." % cid)
    c = claims[cid]
    old = c["status"]
    if old in TERMINAL:
        refuse("%s is %s, and that is final. A %s claim never changes status "
               "again. To take the idea up again, state it as a new claim with "
               "`claims.py new` and cite %s in it; %s stays where it is."
               % (cid, old, old, cid, cid))
    if target == old:
        refuse("%s is already %s, so there is nothing to change. If you meant to "
               "record fresh evidence, demote it to proposed first." % (cid, old))
    if target not in MOVES[old]:
        refuse("%s is %s, and %s cannot become %s. From %s you may only go to "
               "%s. If the evidence no longer holds, demote it to proposed first."
               % (cid, old, old, target, old, ", ".join(sorted(MOVES[old]))))

    evidence = (args.evidence or "").strip()
    is_run = bool(RUN_ID.match(evidence))
    if target == "verified":
        if not evidence:
            refuse("verifying %s needs --evidence naming an ingested run, like "
                   "--evidence R-007. Without a run on record there is nothing "
                   "for anyone to check." % cid)
        if not is_run:
            refuse("a citation makes a claim externally-established, not "
                   "verified. To verify %s, point --evidence at an ingested run "
                   "that checked it. To record the source instead, set %s "
                   "externally-established." % (cid, cid))
        if not run_on_record(problem, evidence):
            refuse("there is no ingested run %s under %s/runs — I looked for its "
                   "RETURN.json. Ingest the run with `run.py ingest` first, then "
                   "verify %s." % (evidence, problem.name, cid))
        if args.actor.strip().casefold() == c["discoverer"].strip().casefold():
            refuse("%s was discovered by %s, so %s cannot verify it. Whoever "
                   "found a result never confirms it. Have a different actor "
                   "check the statement in its own run, and pass that actor to "
                   "--actor." % (cid, c["discoverer"], args.actor))
        ev_model = run_model(problem, evidence)
        disc_run = discovering_run(problem, cid)
        disc_model = run_model(problem, disc_run) if disc_run else None
        if ev_model and disc_model:
            if ev_model == disc_model and not args.accept_same_model:
                refuse("the evidence run %s ran on %s — the same model that "
                       "discovered %s (%s). A model checking its own kind of "
                       "mistake is weak evidence. Prefer a different model; to "
                       "proceed anyway, pass --accept-same-model and the claim "
                       "will record Independence: none." % (evidence, ev_model,
                                                           cid, disc_run))
            if ev_model == disc_model:
                independence = "none (same model, %s)" % ev_model
            elif provider(ev_model) == provider(disc_model):
                independence = "partial (same provider: %s vs %s)" % (disc_model,
                                                                     ev_model)
                print("Warning: discoverer and checker share a provider "
                      "(%s). Recorded as partial independence." % provider(ev_model))
            else:
                independence = "full (%s checked %s)" % (ev_model, disc_model)
        else:
            independence = "unknown (models not on record)"
        if args.rests_on is None and c["rests_on"]:
            print("Note: %s keeps its recorded dependencies: %s. Pass "
                  "--rests-on to change them." % (cid, ", ".join(c["rests_on"])))
        elif args.rests_on is None:
            refuse("verifying %s needs --rests-on: name the claim IDs its "
                   "proof depends on, or say --rests-on none. When a "
                   "dependency later falls, this is how its dependents are "
                   "found — the one hunt this lab has done by hand took four "
                   "hours." % cid)
        if old == "conditional":
            bad = []
            for r in c["rests_on"]:
                st = claims[r]["status"] if r in claims else "not a claim here"
                if st != "verified":
                    bad.append("%s (%s)" % (r, st))
            if bad:
                refuse("%s rests on %s, so it cannot be verified yet. Verify "
                       "what it rests on first, or leave %s conditional."
                       % (cid, "; ".join(bad), cid))
    elif target == "accepted-by-investigator":
        if not evidence:
            refuse("accepting %s on the Investigator's word still needs "
                   "--evidence saying why and when, e.g. \"Investigator "
                   "instruction 2026-08-23: take Steen's theorem as proved; "
                   "thesis embargoed\". The decision is the evidence, and it "
                   "must be on the record." % cid)
        if RUN_ID.match(evidence):
            refuse("%s is a run. accepted-by-investigator records a decision, "
                   "not a run — describe the instruction in --evidence, or set "
                   "the claim verified with that run instead." % evidence)
    elif target == "externally-established":
        if not evidence:
            refuse("recording %s as externally-established needs --evidence with "
                   "the citation — who published it, and where. A claim with no "
                   "source named stays proposed." % cid)
        if is_run:
            refuse("%s is a run of our own, not a citation. Our own run makes a "
                   "claim verified, not externally-established. Pass the "
                   "published source to --evidence, or set %s verified instead."
                   % (evidence, cid))
    elif target == "superseded":
        if not args.by:
            refuse("superseding %s needs --by naming the claim that replaces it, "
                   "like --by C-020. Without it nobody can tell later which claim "
                   "to read instead." % cid)
        if args.by == cid:
            refuse("%s cannot supersede itself. Allocate the sharper claim with "
                   "`claims.py new`, then name it with --by." % cid)
        if args.by not in claims:
            refuse("%s is not a claim in this ledger, so %s cannot point at it. "
                   "Allocate the replacement with `claims.py new` first, then "
                   "supersede %s with --by <new ID>." % (args.by, cid, cid))

    rests = None
    if getattr(args, "rests_on", None) is not None:
        rests = []
        for chunk in args.rests_on:
            rests += [x.strip() for x in chunk.split(",") if x.strip()]
        if rests == ["none"]:
            rests = []
        for r in rests:
            if not CLAIM_ID.match(r):
                refuse("%s is not a claim ID. Use IDs like C-004, or the word "
                       "none." % r)
            if r not in claims:
                refuse("%s rests on %s, which is not a claim in this ledger."
                       % (cid, r))

    view = sections(problem / "claims" / (cid + ".md"))
    statement = view.get("statement", c["statement"]).strip() or c["statement"]
    conditions = view.get("conditions", c["conditions"]).strip()
    if conditions == "None stated.":
        conditions = ""
    if statement != c["statement"] or conditions != c["conditions"]:
        print("Note: the statement or conditions in %s.md differ from the "
              "ledger. Recording the file's wording as the claim's text." % cid)
    rec = {"event": "set", "id": cid, "ts": now(), "actor": args.actor,
           "from": old, "to": target, "evidence": evidence or None,
           "by": args.by, "statement": statement, "conditions": conditions,
           "hash": text_hash(statement, conditions)}
    if target == "verified":
        rec["independence"] = independence
    if rests is not None:
        rec["rests_on"] = rests
    append(problem, rec)
    regenerate(problem)
    tail = " (%s)" % evidence if evidence else (" (by %s)" % args.by if args.by else "")
    commit(problem, "%s %s -> %s%s" % (cid, old, target, tail))
    print("%s %s -> %s" % (cid, old, target))
    if target in ("refuted", "superseded", "proposed"):
        hit = dependents(claims, cid)
        if hit:
            print("Standing on %s, review each: %s" % (cid, ", ".join(hit)))
            for h in hit:
                print("  %s [%s] — %s" % (h, claims[h]["status"],
                                          one_line(claims[h]["statement"])))


def cmd_check(args):
    problem = find_problem(args.problem)
    claims, order = load(problem)
    warnings = []
    for cid in order:
        c = claims[cid]
        for r in c["rests_on"]:
            if r not in claims:
                warnings.append("%s rests on %s, which is not a claim here. "
                                "State %s as a claim of its own, or restate %s "
                                "without it." % (cid, r, r, cid))
        if len(c["history"]) > 1:
            view = sections(problem / "claims" / (cid + ".md"))
            if view:
                cond = view.get("conditions", "").strip()
                cond = "" if cond == "None stated." else cond
                if text_hash(view.get("statement", ""), cond) != c["hash"]:
                    warnings.append("%s.md no longer says what it said when its "
                                    "status last changed. Either restore the "
                                    "wording or set the status again so the new "
                                    "wording goes on record." % cid)
        if c["status"] == "superseded" and not c["superseded_by"]:
            warnings.append("%s is superseded but names no replacement. Set it "
                            "again with --by <ID> so readers know what to read "
                            "instead." % cid)
    if warnings:
        print("%d thing(s) to look at:" % len(warnings))
        for w in warnings:
            print("- " + w)
    else:
        print("Nothing to flag in %d claim(s)." % len(order))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="claims.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="allocate a claim ID and state the claim")
    n.add_argument("--statement", required=True)
    n.add_argument("--conditions", default="")
    n.add_argument("--rests-on", action="append", dest="rests_on",
                   help="claim ID this one depends on; repeat or comma separate")
    n.set_defaults(func=cmd_new)

    s = sub.add_parser("set", help="change a claim's status")
    s.add_argument("claim")
    s.add_argument("status", help="one of: " + ", ".join(STATUSES))
    s.add_argument("--evidence", help="an ingested run ID, a citation, or for "
                                      "accepted-by-investigator the decision")
    s.add_argument("--by", help="for superseded: the claim that replaces this one")
    s.add_argument("--rests-on", action="append", dest="rests_on",
                   help="claim IDs this one's proof depends on (or: none); "
                        "required when verifying a claim with none recorded")
    s.add_argument("--accept-same-model",
                   action="store_true",
                   help="allow evidence from the same model that discovered "
                        "the claim; recorded as Independence: none")
    s.set_defaults(func=cmd_set)

    c = sub.add_parser("check", help="advisory lint; never fails")
    c.set_defaults(func=cmd_check, actor=None)

    for q in (n, s, c):
        q.add_argument("--problem", help="the problem directory (default: found "
                                         "by walking up from here)")
    for q in (n, s):
        q.add_argument("--actor", required=True, help="who is making this change")

    args = p.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
