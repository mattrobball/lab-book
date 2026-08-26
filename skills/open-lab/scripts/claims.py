#!/usr/bin/env python3
"""Claim ledger for one problem.

Per problem: the ledgers under claims/ are the only truth, claims/_ids/ holds
one marker file per allocated ID, and C-NNN.md plus CLAIMS.md are views
rebuilt from them. Every state change is committed, because git is the layer
that makes tampering visible.

One investigator writes one ledger — `claims/ledger-<tag>.jsonl`, with the
founding `claims/ledger.jsonl` read alongside them. A claim's state is its
latest event across every stream. Two people appending to one file conflict
on every push; separate files never do, and nobody has to merge a record by
hand.

This file also holds what both scripts need to know about investigators,
branches and git: one git helper, one tag rule, one branch gate.
"""
import argparse
import hashlib
import json
import os
import re
import socket
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
    "verified": {"conditional", "proposed", "refuted", "superseded"},
    "refuted": set(),
    "superseded": set(),
}
TERMINAL = {"refuted": "refuted", "superseded": "superseded"}
# Both forms of every ID: the namespaced `R-alice-007` an investigator
# allocates, and the bare `R-007` of a lab that started before anyone joined.
# Untagged IDs stay valid and readable for good; nobody renumbers evidence.
RUN_ID = re.compile(r"^R-(?:([a-z0-9][a-z0-9-]*)-)?(\d+)$")
CLAIM_ID = re.compile(r"^C-(?:([a-z0-9][a-z0-9-]*)-)?(\d+)$")
HEADING = re.compile(r"^## +(.+?)\s*$", re.M)
COMMENT = re.compile(r"<!--.*?-->", re.S)
TAG_MAX = 12


LAST_REFUSAL = {"message": None}


def refuse(message):
    LAST_REFUSAL["message"] = message
    sys.stderr.write("Refused: " + message + "\n")
    raise SystemExit(2)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def host():
    return socket.gethostname()


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


def git(root, *args):
    """Every git call in the kit goes through here. LAB_COMMIT marks the
    scripts' own calls so the pre-commit guard lets them through; a hand
    commit carries no such mark."""
    return subprocess.run(["git"] + list(args), cwd=str(root),
                          capture_output=True, text=True,
                          env=dict(os.environ, LAB_COMMIT="1"))


def git_out(root, *args):
    """A git call's stdout, stripped, and "" when the call failed — for the
    questions where "git could not answer" and "the answer is empty" need no
    telling apart."""
    r = git(root, *args)
    return r.stdout.strip() if r.returncode == 0 else ""


def git_root(problem):
    r = git(problem, "rev-parse", "--show-toplevel")
    if r.returncode != 0:
        refuse("%s is not inside a git repository, and git is what makes a "
               "changed ledger visible later. Run `git init` at the top of the "
               "lab and commit what is here, then try again." % problem)
    return Path(r.stdout.strip())


def lab_root(start=None):
    """The top of the lab, found from here. Joining and the meeting are
    lab-wide acts and belong to no single problem."""
    start = Path(start or Path.cwd()).resolve()
    top = git_out(start, "rev-parse", "--show-toplevel")
    if not top:
        refuse("%s is not inside a git repository. Run this from inside the "
               "lab, or `git init` at the top of it first." % start)
    return Path(top)


def lab_config(root):
    """lab.json as a dict, {} when the lab has none."""
    p = Path(root) / "lab.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as e:
        refuse("%s is not valid JSON (%s). Fix that file — it holds the models "
               "and launch commands for this machine, and the lab's "
               "investigators." % (p, e))


# ------------------------------------------------- investigators, branches

def slug(name):
    """An investigator's tag, made from their git user.name. It is short
    because it is written into every ID they allocate, and it is derived
    rather than chosen so that two people cannot pick the same one by
    accident."""
    s = re.sub(r"[^a-z0-9-]+", "", (name or "").lower())
    return re.sub(r"-{2,}", "-", s).strip("-")[:TAG_MAX].strip("-")


def investigators(root):
    return lab_config(root).get("investigators") or {}


def registry_anywhere(root):
    """Every registration this clone can see, on this branch or any
    investigator's. A tag taken on somebody else's branch is taken, and a
    registration made this morning binds before any meeting has merged it."""
    reg = dict(investigators(root))
    for tag, ref in branch_refs(root):
        cfg = read_branch_file(root, ref, "lab.json")
        try:
            more = (json.loads(cfg or "{}").get("investigators") or {})
        except json.JSONDecodeError:
            continue
        for key, value in more.items():
            reg.setdefault(key, value)
    return reg


def joined(root):
    """True once anyone has joined — registered here, or holding a branch of
    their own. Before that the lab is one person's and every rule here stands
    aside: untagged IDs, one ledger, any branch."""
    return bool(investigators(root)) or bool(branch_tags(root))


def git_user(root):
    return git_out(root, "config", "user.name")


def own_tag(root):
    """The caller's tag, from git's own idea of who they are."""
    name = git_user(root)
    if not name:
        refuse("git has no user.name here, and an investigator's tag is made "
               "from their name. Set one — `git config user.name \"Your "
               "Name\"` — then run the same command again.")
    tag = slug(name)
    if not tag:
        refuse("git user.name is %r, which leaves no letters or digits to make "
               "a tag from. Set a name with some in it: `git config user.name "
               "\"Your Name\"`." % name)
    return tag


def own_branch(tag):
    return "lab/%s" % tag


def current_branch(root):
    return git_out(root, "rev-parse", "--abbrev-ref", "HEAD")


def has_ref(root, ref):
    return git(root, "rev-parse", "--verify", "--quiet", ref).returncode == 0


def has_remote(root):
    return bool(git_out(root, "remote"))


def meetings_dir(root):
    return Path(root) / "notebook" / "meetings"


def agenda_path(root, date=None):
    return meetings_dir(root) / ("%s-agenda.md" % (date or today()))


def meeting_open(root):
    """True while today's agenda is on the tree: the room is sitting, and the
    keyboard-holder is recording its decisions on main."""
    return agenda_path(root).exists()


def require_own_branch(root, what):
    """The write gate. Each investigator keeps their own record on their own
    branch; main is what the group has agreed. Everyone committing the record
    to one shared branch spends the day on pushes that are rejected, merged,
    and conflicted over generated files. Returns the caller's tag, or None in
    a lab nobody has joined yet — which is left exactly as it was."""
    if not joined(root):
        return None
    tag = own_tag(root)
    if tag not in registry_anywhere(root):
        refuse("this lab has investigators registered and you are not one of "
               "them, so %s has nowhere to land. Run `run.py join` — it "
               "registers you and puts you on your own branch." % what)
    branch = current_branch(root)
    if branch == own_branch(tag) or (branch == "main" and meeting_open(root)):
        return tag
    refuse("you are on branch %s, and %s is written on your own branch. Run "
           "`run.py join` to check out %s, then run the same command again."
           % (branch or "no branch", what, own_branch(tag)))


def branch_tags(root):
    """Every investigator branch this clone can see, tag to ref, preferring
    origin's copy of each. Read from the refs themselves rather than from
    the registry: a colleague who joined this morning is visible before
    anyone has merged their registration."""
    local, remote = {}, {}
    for line in git_out(root, "for-each-ref", "--format=%(refname:short)",
                        "refs/heads/lab/*",
                        "refs/remotes/origin/lab/*").splitlines():
        ref = line.strip()
        if not ref:
            continue
        (remote if ref.startswith("origin/") else local)[ref.split("/")[-1]] = ref
    out = dict(local)
    out.update(remote)
    return out


def known_tags(root):
    """Every investigator this lab knows of: registered, or holding a branch."""
    return set(investigators(root)) | set(branch_tags(root))


def branch_refs(root, skip=None):
    """(tag, ref) for every investigator branch, one ref each. Reading a
    colleague's record needs no merge and no checkout."""
    return [(tag, ref) for tag, ref in sorted(branch_tags(root).items())
            if tag != skip]


def read_branch_file(root, ref, relpath):
    """One file's text as another branch holds it, without checking that
    branch out. None when the branch has no such file."""
    r = git(root, "show", "%s:%s" % (ref, relpath))
    return r.stdout if r.returncode == 0 else None


def read_branch_json(root, ref, relpath):
    text = read_branch_file(root, ref, relpath)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def list_branch_dir(root, ref, relpath):
    """The names directly under a directory on another branch; [] when the
    branch has no such directory."""
    r = git(root, "ls-tree", "--name-only", ref, relpath.rstrip("/") + "/")
    if r.returncode != 0:
        return []
    return [line.rstrip("/").split("/")[-1]
            for line in r.stdout.splitlines() if line.strip()]


# ---------------------------------------------------------------- ID names

def id_parts(ident):
    """(tag, number) for an ID in either form; None when it is not one. A
    legacy `C-007` carries the empty tag, so the founding stream sorts
    first and stays readable for good."""
    pattern = CLAIM_ID if str(ident).startswith("C-") else RUN_ID
    m = pattern.match(str(ident))
    return (m.group(1) or "", int(m.group(2))) if m else None


def id_tag(ident):
    """The investigator an ID belongs to, "" for the founding stream and
    None when the text is not an ID at all."""
    parts = id_parts(ident)
    return parts[0] if parts else None


def id_key(ident):
    """Sort order for IDs: by tag, then by number. Unreadable IDs sort last
    rather than crashing the listing they appear in."""
    parts = id_parts(ident)
    return (parts[0], parts[1], "") if parts else ("￿", 0, str(ident))


def make_id(kind, tag, number):
    return "%s-%s%03d" % (kind, tag + "-" if tag else "", number)


def first_id(text):
    """The claim ID in a command's output, whatever else it printed beside
    it. Callers read the ID from the line that is only an ID, so a line of
    guidance can be added without breaking them."""
    for line in text.splitlines():
        if CLAIM_ID.match(line.strip()):
            return line.strip()
    return ""


def next_step(cid, status):
    """The one line printed with a new ID saying what would settle it. A
    claim stated and then left at proposed is the commonest way a result
    never becomes evidence."""
    if status == "proposed":
        return ("%s is proposed — stated, nothing settles it. Dispatch a run "
                "that attacks it, then `claims.py set %s verified --evidence "
                "<run> --rests-on <ids|none>` once that run is ingested."
                % (cid, cid))
    return ("%s is %s: recorded on the evidence given, not re-derived here. "
            "Any claim of ours resting on it is conditional until we check it "
            "ourselves." % (cid, status))


def resolve_actor(given, tag):
    """Who a change is credited to. In a lab whose investigators have
    joined, that is the caller's own tag unless they say otherwise; in a lab
    with none, there is nobody to assume, and the credit has to be stated."""
    if given:
        return given
    if not tag:
        refuse("this needs --actor: who is making the change. In a lab whose "
               "investigators have joined it defaults to your own tag, but "
               "nobody has joined here, so say who to credit.")
    return tag


# ---------------------------------------------------------------- ledger

def ledger_path(problem, tag=None):
    """One append-only file per investigator, the untagged one being the
    founding stream. Two people appending to a single file conflict on every
    push, over lines neither of them wrote."""
    name = "ledger-%s.jsonl" % tag if tag else "ledger.jsonl"
    return Path(problem) / "claims" / name


def ledger_paths(problem):
    d = Path(problem) / "claims"
    return sorted(d.glob("ledger*.jsonl")) if d.is_dir() else []


def stream_tag(path):
    """Whose stream a ledger file is; "" for the founding one."""
    m = re.match(r"^ledger(?:-([a-z0-9][a-z0-9-]*))?\.jsonl$", Path(path).name)
    return (m.group(1) or "") if m else ""


def stream_events(problem):
    """Every event in every ledger on disk, each marked with the stream it
    came from."""
    out = []
    for p in ledger_paths(problem):
        tag = stream_tag(p)
        for line in p.read_text().splitlines():
            if line.strip():
                out.append((json.loads(line), tag))
    return out


def remote_events(problem, root=None):
    """The other investigators' ledgers, read straight out of their branches
    and marked with the branch they came from. Read-only: seeing what a
    colleague has recorded must never mean merging their record first."""
    root = Path(root or git_root(problem))
    base = str(Path(problem).resolve().relative_to(root.resolve()))
    base = "" if base == "." else base + "/"
    out = []
    for tag, ref in branch_refs(root):
        for name in list_branch_dir(root, ref, base + "claims"):
            if not (name.startswith("ledger") and name.endswith(".jsonl")):
                continue
            text = read_branch_file(root, ref, base + "claims/" + name) or ""
            for line in text.splitlines():
                if line.strip():
                    out.append((json.loads(line), ref))
    return out


def fold(events):
    """A claim's state is its latest event across every stream. Every `new`
    is folded in before any status change: two streams' clocks need not
    agree, and a change read before the statement it changes would have
    nothing to apply to. Events seen twice — the same commit on two branches
    — are folded once."""
    claims, order, seen = {}, [], set()
    fresh = []
    for rec, branch in events:
        key = json.dumps(rec, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        fresh.append((rec, branch))
    for want_new in (True, False):
        for rec, branch in sorted((e for e in fresh
                                   if (e[0]["event"] == "new") == want_new),
                                  key=lambda e: (e[0]["ts"], e[0]["id"])):
            cid = rec["id"]
            if want_new:
                claims[cid] = {"id": cid, "status": rec["status"],
                               "discoverer": rec["actor"],
                               "statement": rec["statement"],
                               "conditions": rec["conditions"],
                               "rests_on": rec["rests_on"], "hash": rec["hash"],
                               "evidence": None, "confirmed_by": None,
                               "independence": None, "stream": branch,
                               "superseded_by": None, "history": [rec]}
                order.append(cid)
                continue
            c = claims.get(cid)
            if c is None:            # a change whose claim this clone cannot see
                continue
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
    order.sort(key=id_key)
    return claims, order


def load(problem, include_remote=False, root=None):
    """The claims of one problem, merged from every stream. With
    include_remote the other investigators' branches are merged in too, for
    reading only — a local write never touches them."""
    events = stream_events(problem)
    if include_remote:
        events += remote_events(problem, root)
    return fold(events)


def append(problem, rec, tag=None):
    path = ledger_path(problem, tag)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    with os.fdopen(fd, "a") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


def allocate(problem, actor, tag=None):
    """Take the next free ID in the caller's own namespace. O_EXCL means two
    allocators racing here can never walk away with the same one: the loser
    of the creation moves on. Namespaces are what stop two investigators
    minting the same ID on two machines and someone renumbering evidence by
    hand afterwards."""
    ids = Path(problem) / "claims" / "_ids"
    ids.mkdir(parents=True, exist_ok=True)
    mine = tag or ""
    claims, _ = load(problem)
    taken = []
    for name in [p.name for p in ids.iterdir()] + list(claims):
        parts = id_parts(name) if str(name).startswith("C-") else None
        if parts and parts[0] == mine:
            taken.append(parts[1])
    n = max(taken) if taken else 0
    while True:
        n += 1
        cid = make_id("C", mine, n)
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
             "<!-- Generated by claims.py from the ledgers under claims/. Do not",
             "     edit the header by hand, and never change status here. -->", "",
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
            "<!-- Generated by claims.py from the ledgers under claims/. "
            "Do not edit. -->", "",
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
    git(root, "add", "--", *paths)
    r = git(root, "commit", "-m", message, "--", *paths)
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


BROKEN = ("UNINGESTABLE", "HARNESS-FAILURE")


def run_on_record(problem, run_id):
    """None when the run is ingested with a real verdict; otherwise why not.
    A packet on disk is not a run on record: a refused packet still has its
    RETURN.json, and a claim was once promoted on a check run that ingest
    had rejected. Only ingest.json says the gate passed."""
    path = problem / "runs" / run_id / "ingest.json"
    if not path.exists():
        packet = ((problem / "runs" / run_id / "packet" / "RETURN.json").exists()
                  or (problem / "runs" / run_id / "RETURN.json").exists())
        return ("has a packet but was never ingested — a refused packet is not "
                "evidence" if packet else "is not under %s/runs" % problem.name)
    verdict = json.loads(path.read_text()).get("verdict")
    if verdict in BROKEN:
        return "was filed as %s, which is a failure on record, not evidence" % verdict
    return None


# ---------------------------------------------------------------- commands

# The two statuses a claim may be recorded in at birth: neither rests on a
# run of ours, so there is nothing about them for a later command to check.
CITED = ("externally-established", "accepted-by-investigator")


def check_citation(cid, target, evidence):
    """What the two cited statuses need on record. Checked in one place,
    whether the status is given at birth or set later, so the same claim
    cannot enter by the easier door."""
    if target == "accepted-by-investigator":
        if not evidence:
            refuse("accepting %s on the Investigator's word still needs "
                   "--evidence saying why and when, e.g. \"Investigator "
                   "instruction 2026-08-23: take the theorem as proved; the "
                   "thesis is embargoed\". The decision is the evidence, and "
                   "it must be on the record." % cid)
        if RUN_ID.match(evidence):
            refuse("%s is a run. accepted-by-investigator records a decision, "
                   "not a run — describe the instruction in --evidence, or set "
                   "the claim verified with that run instead." % evidence)
    elif target == "externally-established":
        if not evidence:
            refuse("recording %s as externally-established needs --evidence with "
                   "the citation — who published it, and where. A claim with no "
                   "source named stays proposed." % cid)
        if RUN_ID.match(evidence):
            refuse("%s is a run of our own, not a citation. Our own run makes a "
                   "claim verified, not externally-established. Pass the "
                   "published source to --evidence, or set %s verified instead."
                   % (evidence, cid))


def cmd_new(args):
    problem = find_problem(args.problem)
    tag = require_own_branch(git_root(problem), "a new claim")
    actor = resolve_actor(args.actor, tag)
    target = args.status or "proposed"
    evidence = (args.evidence or "").strip()
    if target != "proposed":
        if target not in CITED:
            refuse("a claim is stated as proposed and moves from there. Only "
                   "%s may be recorded in the same breath as the statement, "
                   "because neither rests on work of ours: one cites the "
                   "literature, the other the Investigator's decision. %s needs "
                   "an ingested run that checked it, so state the claim now and "
                   "`claims.py set` it after that run is on record."
                   % (" and ".join(CITED), target))
        check_citation("this claim", target, evidence)
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
    statement, conditions = args.statement.strip(), (args.conditions or "").strip()
    cid = allocate(problem, actor, tag)
    append(problem, {"event": "new", "id": cid, "ts": now(), "actor": actor,
                     "status": "proposed", "statement": statement,
                     "conditions": conditions, "rests_on": rests,
                     "hash": text_hash(statement, conditions)}, tag)
    if target != "proposed":
        # One command, one commit: a claim that is only ever a citation
        # should not need two, and the gap between them is where a claim
        # sits at proposed in the views while the source is already known.
        append(problem, {"event": "set", "id": cid, "ts": now(), "actor": actor,
                         "from": "proposed", "to": target, "evidence": evidence,
                         "by": None, "statement": statement,
                         "conditions": conditions,
                         "hash": text_hash(statement, conditions)}, tag)
    regenerate(problem)
    commit(problem, "%s new (%s)" % (cid, target))
    print(cid)
    print(next_step(cid, target))


def cmd_set(args):
    problem = find_problem(args.problem)
    tag = require_own_branch(git_root(problem), "a status change")
    actor = resolve_actor(args.actor, tag)
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
        why = run_on_record(problem, evidence)
        if why:
            refuse("there is no ingested run %s: it %s. Only a run that `run.py "
                   "ingest` accepted counts, so ingest it clean first, then "
                   "verify %s." % (evidence, why, cid))
        if actor.strip().casefold() == c["discoverer"].strip().casefold():
            refuse("%s was discovered by %s, so %s cannot verify it. Whoever "
                   "found a result never confirms it. Have a different actor "
                   "check the statement in its own run, and pass that actor to "
                   "--actor." % (cid, c["discoverer"], actor))
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
        # A check run by another investigator is worth recording as such: a
        # second lab reaching the same result on its own machine is the
        # independence a second model cannot give.
        if id_tag(evidence) and disc_run and id_tag(disc_run) not in (
                None, id_tag(evidence)):
            independence += ", different lab"
        if args.rests_on is None and c["rests_on"]:
            print("Note: %s keeps its recorded dependencies: %s. Pass "
                  "--rests-on to change them." % (cid, ", ".join(c["rests_on"])))
        elif args.rests_on is None:
            refuse("verifying %s needs --rests-on: name the claim IDs its "
                   "proof depends on, or say --rests-on none. When a "
                   "dependency later falls, this is how its dependents are "
                   "found — the one hunt this lab has done by hand took four "
                   "hours." % cid)
        # Checked on every move to verified, whatever the old status: the
        # check once ran only from conditional, and proposed -> verified
        # walked past unverified dependencies twice in an hour.
        rests_now = c["rests_on"]
        if args.rests_on is not None:
            rests_now = [x.strip() for chunk in args.rests_on
                         for x in chunk.split(",") if x.strip()]
            if rests_now == ["none"]:
                rests_now = []
        bad = []
        for r in rests_now:
            st = claims[r]["status"] if r in claims else "not a claim here"
            if st != "verified":
                bad.append("%s (%s)" % (r, st))
        if bad:
            refuse("%s rests on %s, so it cannot be verified yet. Verify "
                   "what it rests on first, or set %s conditional."
                   % (cid, "; ".join(bad), cid))
    elif target in CITED:
        check_citation(cid, target, evidence)
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
    rec = {"event": "set", "id": cid, "ts": now(), "actor": actor,
           "from": old, "to": target, "evidence": evidence or None,
           "by": args.by, "statement": statement, "conditions": conditions,
           "hash": text_hash(statement, conditions)}
    if target == "verified":
        rec["independence"] = independence
    if rests is not None:
        rec["rests_on"] = rests
    append(problem, rec, tag)
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


def cmd_rebuild(args):
    """Rebuild this problem's claim views from every stream on this branch.
    After a merge the generated pages hold one branch's version of a record
    that now has two; a page rebuilt from the ledgers is never merged by
    hand, and never has to be."""
    problem = find_problem(args.problem)
    git_root(problem)
    regenerate(problem)
    commit(problem, "rebuild: claim views")
    claims, order = load(problem)
    print("Rebuilt CLAIMS.md and %d claim page(s) from %d stream(s)."
          % (len(order), len(ledger_paths(problem))))
    return 0


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
    n.add_argument("--status", default="proposed",
                   help="record the claim straight into %s, in one command "
                        "with its --evidence; every other status is reached "
                        "with `set`" % " or ".join(CITED))
    n.add_argument("--evidence", help="with --status: the citation, or the "
                                      "Investigator's recorded decision")
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

    b = sub.add_parser("rebuild", help="regenerate the claim views from the "
                                       "ledgers; changes nothing else")
    b.set_defaults(func=cmd_rebuild, actor=None)

    for q in (n, s, c, b):
        q.add_argument("--problem", help="the problem directory (default: found "
                                         "by walking up from here)")
    for q in (n, s):
        q.add_argument("--actor", help="who is making this change (default: "
                                       "your investigator tag, once anyone "
                                       "has joined the lab)")

    args = p.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
