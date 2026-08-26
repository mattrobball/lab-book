#!/usr/bin/env python3
"""Runs: dispatch a worker, ingest what it returns, keep the notebook.

new      allocate a run ID, record dispatch.json and execution.json, assemble
         PROMPT.md and the run-local worker charter, launch the worker.
ingest   gate the returned packet, replay its evidence, allocate proposed
         claims, file the notebook entry, commit.
lint     read-only packet contract check; workers run it before finishing.
void     close a run that produced nothing, with the reason on record.
waive-review  record that an owed review will not happen, with the reason.
note     file a Director-written entry: headline, body, actor. No packet.
catchup  what changed since a commit or a date, plus the standing lints:
         runs needing attention, reviews owed, unresolved duplicate warnings,
         claims resting on unverified claims, per-model totals — and, in a
         lab with more than one investigator, what the others have recorded.
join     register this investigator and put them on their own branch.
whoami   who this clone thinks you are, and what you have not pushed.
rebuild  regenerate every generated view from the record. Nothing else.
reconcile  the meeting: merge every investigator's branch into main, print
         and file the agenda, then record what the room decided.

Claim IDs, status and the ledger belong to claims.py; this file imports it and
never touches claims/ by hand.

Three conventions this file settles:

* The replay command is the first fenced or indented code block inside the
  packet's `## Validation` section, whole: one shell script under `set -e`,
  with the run directory as its working directory, under the timeout recorded
  at dispatch.
* Replay and review are recorded as facts, never ranked. `replayed` is
  computed here — exit 0 inside the timeout and every marker present as an
  exact substring — and never copied from the worker. A marker proves a print
  statement ran, nothing more; what the replay recomputes is what it is worth.
  `reviewed_by` lists the referee runs that later checked this one.
* The fence is judged only against what this worker could have written:
  uncommitted files outside its allowed paths, excluding other runs'
  directories. Committed history is never consulted, so nothing the Director
  or a sibling run commits can implicate a worker.
* A packet that fails a gate is refused, not filed, and the refusal text is
  saved to the run directory as refusal.txt. Filing the failure is a separate
  deliberate act: `ingest R-NNN --record-broken` files a packet that exists
  under verdict UNINGESTABLE, or, when the worker never produced one, under
  verdict HARNESS-FAILURE — with the recorded reason either way, and no
  claims. What a refused packet proposed is quoted in the entry as untrusted
  text, so a refusal never silently destroys a lead.
"""
import argparse
import contextlib
import glob as globbing
import gzip
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import claims                                    # noqa: E402  (sibling script)
from claims import (refuse, now, today, host, git, git_out, git_root,   # noqa: E402
                    lab_root, lab_config, investigators, joined, slug,
                    own_tag, own_branch, current_branch, has_ref, has_remote,
                    require_own_branch, branch_refs, read_branch_file,
                    read_branch_json, list_branch_dir, id_tag, id_key,
                    make_id, meetings_dir, agenda_path,
                    branch_tags, known_tags, RUN_ID)

# A claim ID as it appears inside prose — a brief, a STATUS.md line — in
# either form: an investigator's `C-alice-004` or the founding `C-004`.
CLAIM_ID = re.compile(r"\bC-(?:[a-z0-9][a-z0-9-]*-)?\d+\b")
VERDICT_LINE = re.compile(r"^#\s*VERDICT:\s*(PASS|FAIL|UNDECIDED)\s*$")
FENCE = re.compile(r"```[a-zA-Z0-9]*\n(.+?)\n```", re.S)
INDENTED = re.compile(r"^(?: {4}|\t)(\S.*)$", re.M)
INDEX_META = re.compile(r"<!-- index: (.*?) -->")
SECTIONS = ["What was done", "Not claimed", "Leads", "Validation"]
REQUIRED = ["headline", "exits", "validation", "machine_markers",
            "claims_used", "claims_proposed"]
STOP = {"the", "a", "an", "of", "is", "in", "on", "for", "to", "and", "at",
        "has", "have", "every", "all", "with", "that", "this", "it", "are"}

CHARTER = """## Who you are

You are the Technician on run {rid}. You were dispatched to do one task and
return a packet saying what happened. You have no history here and no other
context: this prompt is everything you were given. Do the task in front of you
and nothing else.

## Your fence

{fence}

Anything written outside that makes this run unusable, and the run is refused
at ingest rather than filed. Write nothing outside this repository either —
no /tmp, no home directory; scratch files belong in your packet directory.

- Run no `git` commands of any kind. The lab records itself.
- Never invent a claim ID. Copy into `claims_used` exactly the IDs the brief
  pastes, and nothing else. New claims go in `claims_proposed` as plain
  sentences; the lab allocates their IDs when this run is ingested.
- Do not name yourself anywhere in the packet. The lab stamps who ran this.

## What you must return

Both of these files, under `{packet}`:

`RESULT.md`

- Create this file first, with the first line `# VERDICT: PENDING`, and fill
  the sections in as you work — never save the writing for the end. A worker
  that dies mid-task then leaves its partial findings instead of nothing.
  Replace PENDING with the real verdict as your last act; a packet still
  reading PENDING cannot be ingested.
- The final first line is exactly `# VERDICT: PASS`, `# VERDICT: FAIL` or
  `# VERDICT: UNDECIDED`, then one sentence saying what happened.
- `## What was done` — what you actually did, in order, closely enough that
  someone could follow it.
- `## Not claimed` — what this does not establish: conditions you assumed
  rather than checked, numbers you were handed, cases you did not cover. This
  section is graded; a narrow honest boundary beats a loud headline.
- `## Leads` — approaches you dropped and why, directions that looked
  promising but were outside this task, and what you would try next. "None."
  is an acceptable answer; an empty section is not.
- `## Validation` — keep exactly one of two blocks. A **replay** block: the
  exact command in an indented code block, the exact strings it prints when it
  passes, and what it prints when it fails. Or a **review** block: what a
  referee other than you must check, step by step. The replay block is run
  whole, as one shell script in which every line must succeed, with this
  directory as its working directory, under a {timeout}s timeout.

`RETURN.json` — plain JSON, no comments:

- `headline` — one sentence, the same result the verdict line states.
- `exits` — the states you actually reached, as short strings.
- `validation` — `replay` or `review`, matching the block above.
- `machine_markers` — the exact strings a passing replay prints; ingest looks
  for each one character for character, never by pattern.
- `claims_used` — the claim IDs copied from the brief.
- `claims_proposed` — new claims as plain statements, never IDs.
- `reviewed` — only when your brief asked you to check another run: the run
  IDs you refereed, e.g. `["R-030"]`. Omit it for any other kind of run.
  Without it the run you checked stays flagged as unreviewed, however
  complete your check was.

## Before you finish

Run `python3 <lab root>/run.py lint {rid}` from anywhere in the lab. It is
read-only and prints exactly what the packet contract still needs. Do not
finish until it passes.

## The honest stop

If you cannot finish, return `UNDECIDED` and name the blocker precisely: what
you tried, where it stopped, what would unblock it. A worker that stops
honestly has succeeded and is graded as one. A manufactured PASS is the
expensive failure.
"""


# ---------------------------------------------------------------- locating

def find_problem(explicit):
    """claims.py's rule, plus runs/ and notebook/ as evidence of a problem."""
    if explicit:
        return claims.find_problem(explicit)
    here = Path.cwd().resolve()
    for d in [here] + list(here.parents):
        if any((d / m).is_dir() for m in ("claims", "runs", "notebook")):
            return d
        if d.parent.name == "problems" or (d / ".git").exists():
            break
    return claims.find_problem(None)              # refuses in its own words


def rel(path, root):
    try:
        return str(Path(path).resolve().relative_to(root))
    except ValueError:
        return None


def fingerprint(text):
    return hashlib.sha256(" ".join(text.split()).lower().encode()).hexdigest()


def split_sections(text):
    parts = claims.HEADING.split(text)
    return {parts[i].strip().lower(): parts[i + 1].strip()
            for i in range(1, len(parts) - 1, 2)}


# ---------------------------------------------------------------- git

def director_session():
    return (os.environ.get("LAB_SESSION")            # explicit wins
            or os.environ.get("CLAUDE_CODE_SESSION_ID") or "unknown")


# ------------------------------------------------- the lab and its branches

def all_problems(root):
    """Every problem in the lab: the directories under problems/, and the
    root itself when the lab holds a single problem at its top."""
    out = []
    d = Path(root) / "problems"
    if d.is_dir():
        out += [p for p in sorted(d.iterdir()) if p.is_dir()
                and any((p / m).is_dir() for m in ("claims", "runs", "notebook"))]
    if any((Path(root) / m).is_dir() for m in ("claims", "runs")):
        out.append(Path(root))
    return out


def problem_rel(root, problem):
    """A problem's path as the other branches spell it — the prefix every
    `git show <ref>:<path>` needs."""
    rel = str(Path(problem).resolve().relative_to(Path(root).resolve()))
    return "" if rel == "." else rel + "/"


def fetch(root):
    """Bring the other branches up to date before reading them. Offline is
    normal and never fatal: one line, and the report is of what is on disk."""
    if not has_remote(root):
        return False
    r = git(root, "fetch", "origin", "--prune")
    if r.returncode != 0:
        print("Could not reach origin (%s). What follows is what this clone "
              "already had."
              % (r.stderr.strip().splitlines() or ["no reason given"])[-1][:100])
        return False
    return True


def unpushed(root, tag):
    """How many commits this investigator has that origin has not. A record
    that exists only on one laptop is a record the group cannot read."""
    if not tag or not has_remote(root):
        return None
    remote = "origin/" + own_branch(tag)
    if not has_ref(root, remote):
        return None
    out = git_out(root, "rev-list", "--count", "%s..%s"
                  % (remote, own_branch(tag)))
    return int(out) if out.isdigit() else None


MEETING_PREFIX = "meeting: "


def last_meeting(root):
    """(commit, time) of the meeting that last agreed the record, read off
    main; (None, None) before the first one, when everything counts as new.
    The meeting is the line the group draws under what it has read."""
    if not has_ref(root, "main"):
        return None, None
    sha = git_out(root, "log", "main", "-1", "--format=%H",
                  "--extended-regexp", "--grep", "^" + MEETING_PREFIX)
    return (sha, commit_time(root, sha)) if sha else (None, None)


def find_run_anywhere(root, problem, rid):
    """Where a run can be read: this tree, or a branch this clone has
    fetched. A record that cites a run existing nowhere is a dead reference
    nobody can follow back."""
    if (run_dir(problem, rid) / "dispatch.json").exists():
        return "here"
    base = problem_rel(root, problem)
    for tag, ref in branch_refs(root):
        if read_branch_file(root, ref, base + "runs/%s/dispatch.json" % rid):
            return ref
    return None


def run_record_anywhere(root, problem, rid):
    """A run's dispatch.json wherever it can be read from, for the questions
    asked about somebody else's run — is it still open, who owns it."""
    local = load_json(run_dir(problem, rid) / "dispatch.json")
    if local:
        return local
    base = problem_rel(root, problem)
    for tag, ref in branch_refs(root):
        d = read_branch_json(root, ref, base + "runs/%s/dispatch.json" % rid)
        if d:
            return d
    return None


def rotation_notice(problem, root):
    """After N ingests in one Director session, say so — once per ingest,
    never enforced. Rotation is the Investigator's call."""
    sid = director_session()
    if sid == "unknown":
        return
    limit = ((lab_config(root).get("machine") or {}).get("rotate_after_ingests")
             or 12)
    n = len([1 for rid, _ in all_runs(problem)
             if (ingest_record(problem, rid) or {}).get("director_session") == sid])
    if n >= limit:
        print("This Director session has ingested %d run(s) in this problem "
              "(rotate_after_ingests is %d). Judgment degrades with context "
              "before it shows; one lab's worst hour was its longest "
              "session. Propose rotation to the Investigator with this reason "
              "and rotate on their word — the steps are in AGENTS.md."
              % (n, limit))


HOOK_MARK = "open-lab guard-commit"
RUN_DIR = re.compile(r"^((?:.*/)?)runs/([^/]+)/")


def install_hook(root):
    """The pre-commit guard, one file, written once per clone. A run's files
    enter the record once, at ingest; seven hand commits in one day swept
    open runs' half-written packets and mid-run logs into unrelated
    amendments, one of them half a million lines."""
    hooks = git(root, "rev-parse", "--git-path", "hooks").stdout.strip()
    if not hooks:
        return None
    hooks = Path(hooks) if os.path.isabs(hooks) else root / hooks
    hook = hooks / "pre-commit"
    if hook.exists():
        return hook if HOOK_MARK in hook.read_text(errors="replace") else None
    hooks.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\n# %s: a run's files enter the record once, at "
                    "ingest.\nexec %s %s guard-commit\n"
                    % (HOOK_MARK, shlex.quote(sys.executable),
                       shlex.quote(str(Path(__file__).resolve()))))
    hook.chmod(0o755)
    return hook


def guard_foreign_runs(root, staged):
    """Another investigator's run directory is read-only to you, open or
    closed. An experiment belongs to whoever ran it; others cite it. Editing
    a colleague's evidence is a change nobody can see coming and nobody can
    attribute afterwards."""
    if not joined(root):
        return
    mine = slug(claims.git_user(root))
    foreign = {}
    for p in staged:
        m = RUN_DIR.match(p)
        if not m:
            continue
        owner = id_tag(m.group(2))
        if owner and owner != mine:
            foreign.setdefault(m.group(2), []).append(p)
    if not foreign:
        return
    sys.stderr.write(
        "Refused: this commit stages files under another investigator's runs "
        "— %s. A run belongs to whoever dispatched it: cite it by ID, and "
        "dispatch your own run for anything it should have done differently. "
        "Take those paths out of the commit.\n"
        % "; ".join("%s (%s, owner %s)" % (rid, ps[0], id_tag(rid))
                    for rid, ps in sorted(foreign.items())))
    sys.exit(1)


GITIGNORE_LINES = ("__pycache__/", "*.pyc")


def ensure_gitignore(root):
    """Byte-compiled Python is not a record. Every uncommitted file counts
    against the worker whose run is being ingested, and a stray .pyc left
    under a run directory implicates a worker that never wrote it. Written
    once, appended to if the file exists without these lines."""
    path = Path(root) / ".gitignore"
    text = path.read_text() if path.exists() else ""
    missing = [l for l in GITIGNORE_LINES if l not in text.splitlines()]
    if not missing:
        return False
    head = "" if text else ("# Byte-compiled files are not part of the "
                            "record.\n")
    tail = "" if not text or text.endswith("\n") else "\n"
    path.write_text(text + tail + head + "\n".join(missing) + "\n")
    return True


def cmd_guard_commit(args):
    """Run by the pre-commit hook. Refuses a commit that stages a file under
    an open run's directory, or under a run belonging to somebody else,
    unless the scripts made it."""
    if os.environ.get("LAB_COMMIT") == "1":
        return
    root = Path(os.getcwd())
    top = git(root, "rev-parse", "--show-toplevel").stdout.strip()
    if top:
        root = Path(top)
    staged = git(root, "diff", "--cached", "--name-only").stdout.splitlines()
    guard_foreign_runs(root, staged)
    hits = {}
    for p in staged:
        m = RUN_DIR.match(p)
        if not m:
            continue
        rundir = root / m.group(1) / "runs" / m.group(2)
        try:
            d = json.loads((rundir / "dispatch.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if d.get("status") == "open":
            hits.setdefault(m.group(2), []).append(p)
    if not hits:
        return
    sys.stderr.write(
        "Refused: this commit stages files of runs still open — %s. A run's "
        "files enter the record once, through `run.py ingest`, with its "
        "verdict; a hand commit of a live worker's directory puts half-written "
        "packets and mid-run logs in the history under an unrelated subject. "
        "Name the paths you mean to commit (never -a or -A), or ingest/void "
        "the run first.\n"
        % "; ".join("%s (%s)" % (rid, ", ".join(ps[:3]) + (", …" if len(ps) > 3 else ""))
                    for rid, ps in sorted(hits.items())))
    sys.exit(1)



def head(root):
    r = git(root, "rev-parse", "HEAD")
    if r.returncode != 0:
        refuse("this repository has no commits yet, so there is no position to "
               "record for the dispatch. Commit what is here first, then "
               "dispatch.")
    return r.stdout.strip()


def dirty(root):
    """Every uncommitted path, file by file (-uall): git otherwise collapses
    a wholly untracked directory into one entry, and a sibling problem's
    untracked runs/ then looks like a stray write."""
    out = set()
    for line in git(root, "status", "--porcelain", "-uall").stdout.splitlines():
        p = line[3:]
        if " -> " in p:
            p = p.split(" -> ")[-1]
        out.add(p.strip().strip('"'))
    return out


def commit(root, paths, message):
    # A path that is gone is still committed when git tracks it: deleting a
    # file is a change to record like any other.
    paths = [p for p in paths if p and ((root / p).exists() or
             git(root, "ls-files", "--error-unmatch", "--", p).returncode == 0)]
    if not paths:
        return
    git(root, "add", "--", *paths)
    r = git(root, "commit", "-m", message, "--", *paths)
    if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr):
        refuse("git would not record this change:\n%s\nFix the repository "
               "(usually an unset user.name or user.email), then run the same "
               "command again." % (r.stdout + r.stderr).strip())


def outside(paths, allowed):
    bad = []
    for p in sorted(paths):
        if not any(p == a or p.startswith(a.rstrip("/") + "/") for a in allowed):
            bad.append(p)
    return bad


def commit_time(root, ref):
    r = git(root, "show", "-s", "--format=%ct", ref)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    stamp = int(r.stdout.strip().splitlines()[-1])
    return datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- runs

def run_dir(problem, rid):
    return problem / "runs" / rid


def allocate_run(problem, tag=None):
    """Take the next free run ID in the caller's own namespace. mkdir is
    atomic: two dispatchers racing here cannot both take the ID, and two
    investigators on two machines never reach for the same one at all."""
    d = problem / "runs"
    d.mkdir(parents=True, exist_ok=True)
    mine = tag or ""
    taken = [parts[1] for parts in (id_tag_parts(p.name) for p in d.iterdir())
             if parts and parts[0] == mine]
    n = max(taken) if taken else 0
    while True:
        n += 1
        rid = make_id("R", mine, n)
        try:
            (d / rid).mkdir()
        except FileExistsError:
            continue
        return rid


def id_tag_parts(name):
    return claims.id_parts(name) if RUN_ID.match(str(name)) else None


def all_runs(problem):
    d = problem / "runs"
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.iterdir(), key=lambda p: id_key(p.name)):
        if RUN_ID.match(p.name) and (p / "dispatch.json").exists():
            out.append((p.name, json.loads((p / "dispatch.json").read_text())))
    return out


def run_owner(problem, rid):
    """The investigator a run belongs to: what the dispatch recorded, else
    what its ID says. "" for a run from before anyone joined."""
    d = load_json(run_dir(problem, rid) / "dispatch.json") or {}
    return d.get("investigator") or id_tag(rid) or ""


def require_owner(problem, root, rid, what):
    """A run is closed by whoever opened it. Two people writing verdicts into
    one run leaves a record with two answers and no way to tell which came
    first. A run from before the lab had investigators belongs to nobody, so
    anyone registered may close it — and is told so."""
    if not joined(root):
        return None
    mine = require_own_branch(root, what)
    owner = run_owner(problem, rid)
    if not owner:
        print("%s carries no investigator tag — it is from the founding "
              "stream, which anyone registered may close. Closing it as %s."
              % (rid, mine))
        return mine
    if owner != mine:
        refuse("%s belongs to %s, and %s is theirs to do. Another "
               "investigator's run is cited, never edited: ask them for it, "
               "or dispatch your own run and cite theirs in the brief."
               % (rid, owner, what))
    return mine


def load_json(path):
    """A JSON file, or None when it is missing or unreadable. Half the
    records this script reads may legitimately not be there yet."""
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return None


def push_own_branch(root, tag):
    """Best effort, after every write. The record is already committed; a
    remote that cannot be reached must never cost the writer their commit,
    so a failure is one line and catchup counts what is still unpushed."""
    if not tag or not has_remote(root):
        return
    r = git(root, "push", "origin", own_branch(tag))
    if r.returncode != 0:
        print("Not pushed to origin: %s. The record is committed here; "
              "catchup counts what is unpushed."
              % (r.stderr.strip().splitlines() or ["no reason given"])[-1][:120])


def ingest_record(problem, rid):
    return load_json(run_dir(problem, rid) / "ingest.json")


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------- notebook

def slugify(text, words=6):
    return "-".join(re.findall(r"[a-z0-9]+", text.lower())[:words]) or "entry"


def file_entry(problem, headline, meta, body, tag=None):
    """One entry, written once. The writer's tag is part of the name: two
    investigators filing on one day would otherwise reach for the same
    number, and two different entries under one name is a collision only a
    hand merge can undo."""
    d = problem / "notebook" / "entries"
    d.mkdir(parents=True, exist_ok=True)
    day = time.strftime("%Y%m%d", time.gmtime())
    stem = "N-%s-%s" % (day, tag + "-" if tag else "")
    n = 1 + len([p for p in d.iterdir() if p.name.startswith(stem)])
    path = d / ("%s%02d-%s.md" % (stem, n, slugify(headline)))
    path.write_text("# %s — %s\n\n<!-- index: %s -->\n<!-- Generated by "
                    "run.py. Entries are written once; a correction is a new "
                    "entry filed beside this one. -->\n\n%s\n"
                    % (path.stem, headline, meta, body.strip()))
    regenerate_index(problem)
    return path


def regenerate_index(problem):
    d = problem / "notebook" / "entries"
    rows = ["# Notebook index", "",
            "<!-- Generated by run.py from notebook/entries/. Do not edit. -->", ""]
    for p in sorted(d.glob("N-*.md")):
        m = INDEX_META.search(p.read_text())
        rows.append("- [%s](entries/%s) — %s"
                    % (p.stem, p.name, m.group(1).strip() if m else "—"))
    if len(rows) == 4:
        rows.append("- No entries yet.")
    (problem / "notebook" / "INDEX.md").write_text("\n".join(rows) + "\n")


# ---------------------------------------------------------------- execution

# The shapes workers print their token counts in: the word before the
# number or after it, with or without a separator. A count that is only
# reported one way is a count missing from every other worker's record.
NUMBER = r"[\d,.]+\s*[KkMm]?"
DEFAULT_USAGE = (r"tokens(?:\s+used)?\s*[:=]?\s*(%s)"
                 r"|(%s)\s*(?:total\s+)?tokens" % (NUMBER, NUMBER))


def extract_usage(log, pattern):
    """Best-effort resource accounting. lab.json roles may set usage_pattern,
    a regex with named groups (tokens, cost) run over the worker log; absent
    that, a bare default catches the common 'N tokens' print. Missing numbers
    stay missing — never guessed."""
    if not log.exists():
        return None
    try:
        text = log.read_text(errors="replace")[-20000:]
    except OSError:
        return None
    pat = pattern or DEFAULT_USAGE
    try:
        hits = list(re.finditer(pat, text))
    except re.error:
        return None
    if not hits:
        return None
    m = hits[-1]
    usage = {}
    groups = m.groupdict()
    if groups:
        usage = {k: v for k, v in groups.items() if v}
    elif m.groups():
        # The default pattern spells the count more than one way; whichever
        # alternative matched is the number.
        hit = next((g for g in m.groups() if g), None)
        if hit:
            usage["tokens"] = hit.strip()
    return usage or None


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


@contextlib.contextmanager
def ingest_lock(root):
    """One ingest transaction at a time. On contention we wait instead of
    corrupting .git/index, which once needed a hand rollback."""
    lock = root / ".ingest.lock"
    deadline = time.time() + 120
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if time.time() > deadline:
                refuse("another ingest has held %s for over two minutes. If "
                       "it crashed, remove the file and run this again." % lock)
            time.sleep(1)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            os.unlink(str(lock))


def execution_record(problem, rid):
    return load_json(run_dir(problem, rid) / "execution.json")


def resource_line(problem, rid):
    e = execution_record(problem, rid)
    if not e:
        return None
    bits = []
    if e.get("wall_seconds") is not None:
        bits.append("%dm%02ds wall" % divmod(e["wall_seconds"], 60))
    for k, v in sorted((e.get("usage") or {}).items()):
        bits.append("%s %s" % (v, k))
    return " · ".join(bits) if bits else None


# ---------------------------------------------------------- transcripts

TRANSCRIPT_NAME = "session.jsonl.gz"
TRANSCRIPT_GRACE = 120          # a session file is flushed a moment late
DEFAULT_MAX_MB = 20


def transcript_setting(root, role):
    """A role's transcript rule from lab.json, {} when it has none. The
    patterns live in the lab's own configuration because every worker
    command stores its session somewhere different, and a pattern compiled
    into this script goes stale the first time one of them moves."""
    return ((lab_config(root).get("roles") or {}).get(role) or {}).get(
        "transcript") or {}


def expand_pattern(pattern, rundir):
    """The configured glob with the run directory filled in. Three spellings
    are offered because the stores that name a folder after the working
    directory each mangle it differently."""
    cwd = str(Path(rundir).resolve())
    for key, value in (("{cwd_urlencoded}", urllib.parse.quote(cwd, safe="")),
                       ("{cwd_dashed}", cwd.replace("/", "-")),
                       ("{cwd}", cwd)):
        pattern = pattern.replace(key, value)
    return os.path.expanduser(pattern)


def run_window(problem, rid, d):
    """When the worker was alive, as epoch seconds. A session file written
    before the dispatch or long after the run ended is another run's, and
    filing it here would put one worker's reasoning under another's verdict."""
    def epoch(stamp):
        try:
            return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc).timestamp()
        except (TypeError, ValueError):
            return None
    e = execution_record(problem, rid) or {}
    start = epoch(e.get("start")) or epoch(d.get("ts")) or 0
    end = epoch(e.get("end")) or time.time()
    return start, end + TRANSCRIPT_GRACE


def first_line_cwd(path):
    """The working directory a session file names in its first line, if it
    names one. Some commands put it at the top level and others nest it one
    level down inside that record, so both are looked at; a rule that knew
    only the flat shape found nothing at all for half the workers."""
    try:
        with open(path, errors="replace") as fh:
            rec = json.loads(fh.readline())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(rec, dict):
        return None
    if isinstance(rec.get("cwd"), str):
        return rec["cwd"]
    for value in rec.values():
        if isinstance(value, dict) and isinstance(value.get("cwd"), str):
            return value["cwd"]
    return None


def discover_transcript(problem, root, rid, d):
    """The worker's own session file, found by the rule its role carries.
    None when the role names no rule, or nothing matches inside the run's
    own window."""
    setting = transcript_setting(root, d.get("role"))
    pattern, rule = setting.get("glob"), setting.get("match") or "path"
    if not pattern:
        return None
    if rule not in ("path", "first-line-cwd"):
        print("roles.%s.transcript.match is %r; it must be `path` or "
              "`first-line-cwd`, so no transcript was looked for."
              % (d.get("role"), rule))
        return None
    rundir = run_dir(problem, rid).resolve()
    start, end = run_window(problem, rid, d)
    hits = []
    for p in globbing.glob(expand_pattern(pattern, rundir), recursive=True):
        try:
            mtime = os.path.getmtime(p)
        except OSError:
            continue
        if not start <= mtime <= end:
            continue
        if rule == "first-line-cwd":
            named = first_line_cwd(p)
            if not named or Path(named).resolve() != rundir:
                continue
        hits.append((mtime, p))
    return Path(max(hits)[1]) if hits else None


def digest_and_gzip(path):
    """(sha256 of the file as it stands, its size, its gzipped bytes) in one
    read. The hash is of the original bytes, so a stored copy can be checked
    against the file it came from even after the store has pruned it."""
    h, buf, size = hashlib.sha256(), io.BytesIO(), 0
    # mtime 0: the same transcript stored twice is the same blob, so a
    # re-store shows in the history only when the transcript really changed.
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as out, \
            open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
            out.write(chunk)
            size += len(chunk)
    return h.hexdigest(), size, buf.getvalue()


def attach_transcript(problem, root, rid, d, override=None):
    """Copy the worker's own transcript into the run and describe it for
    ingest.json. The stdout log says what a worker printed; the reasoning
    and tool calls behind a result live in one command's private store, on
    one machine, pruned on its own schedule — and the runs that most need
    explaining later are the ones filed broken. Never refuses: a missing
    transcript is a thinner record, not a bad one."""
    setting = transcript_setting(root, d.get("role"))
    if override:
        source = Path(override).expanduser()
        if not source.is_file():
            refuse("--transcript names %s and there is no file there. Name the "
                   "session file this worker wrote, or drop the flag and let "
                   "the role's rule find it." % override)
    else:
        source = discover_transcript(problem, root, rid, d)
    if source is None:
        if setting.get("glob"):
            print("No transcript found for %s under roles.%s.transcript "
                  "(nothing matched inside the run's own window). The run is "
                  "filed without one." % (rid, d.get("role")))
        return None
    sha, size, blob = digest_and_gzip(source)
    record = {"source": str(source), "sha256": sha, "bytes": size,
              "gzipped_bytes": len(blob), "stored": False}
    cap = (lab_config(root).get("transcripts") or {}).get("max_mb")
    cap = DEFAULT_MAX_MB if cap is None else cap
    if record["gzipped_bytes"] > cap * 1024 * 1024:
        print("%s's transcript is %.1f MB gzipped, over transcripts.max_mb "
              "(%s), so it stays where it is: %s. Its hash and size are on "
              "record; copy it by hand if that machine is going away."
              % (rid, record["gzipped_bytes"] / 1048576.0, cap, source))
        return record
    (run_dir(problem, rid) / TRANSCRIPT_NAME).write_bytes(blob)
    record["stored"] = True
    print("Transcript stored: %s (%d bytes, %d gzipped) from %s."
          % (TRANSCRIPT_NAME, size, record["gzipped_bytes"], source))
    return record


POLL_SECONDS = float(os.environ.get("LAB_POLL_SECONDS", "10"))


def tree_rss_kb(root_pid):
    """Resident memory of a process and everything under it, in KB, from
    one `ps` call. None when ps is unavailable."""
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,rss="],
                             capture_output=True, text=True).stdout
    except OSError:
        return None
    kids, rss = {}, {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        try:
            p, pp, r = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            continue
        kids.setdefault(pp, []).append(p)
        rss[p] = r
    total, stack, seen = 0, [int(root_pid)], set()
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        total += rss.get(p, 0)
        stack.extend(kids.get(p, []))
    return total


def watch(proc, execution, path, t0, limits):
    """The wait that keeps its eyes open. Every POLL_SECONDS it checks wall
    time and the process tree's memory against the dispatch's limits and
    records a breach in execution.json, once per kind, with what it saw.
    It never kills: whether a worker over budget dies or runs on is the
    Investigator's decision, surfaced by overdue_report at every step.
    Blind waiting is what let a worker run 30x over its memory budget on
    a shared machine, twice."""
    while True:
        code = proc.poll()
        if code is not None:
            return code
        elapsed = time.time() - t0
        rss = tree_rss_kb(proc.pid)
        changed = False
        if rss is not None and rss // 1024 > execution.get("peak_rss_mb", 0):
            execution["peak_rss_mb"] = rss // 1024
            changed = True
        seen = {b["kind"] for b in execution.get("breaches", [])}
        breach = None
        if (limits.get("worker_timeout") and "timeout" not in seen
                and elapsed > limits["worker_timeout"]):
            breach = {"kind": "timeout", "limit": limits["worker_timeout"],
                      "seen": int(elapsed), "unit": "s"}
        elif (limits.get("memory_gb") and rss is not None and "memory" not in seen
              and rss / (1024.0 * 1024.0) > limits["memory_gb"]):
            breach = {"kind": "memory", "limit": limits["memory_gb"],
                      "seen": round(rss / (1024.0 * 1024.0), 3), "unit": "GB"}
        if breach:
            breach["at"] = now()
            execution.setdefault("breaches", []).append(breach)
            changed = True
            print("%s is over its %s budget: %s %s seen, limit %s. It has not "
                  "been touched — the Investigator decides: `kill %s`, or let "
                  "it run." % (execution["run"], breach["kind"], breach["seen"],
                               breach["unit"], breach["limit"], proc.pid))
            sys.stdout.flush()
        if changed:
            write_json(path, execution)
        time.sleep(POLL_SECONDS)


def overdue_report(problem, skip=()):
    """Printed at the end of new and ingest, so a stalled run cannot hide
    behind a lint nobody runs. Every line names its remedy."""
    lines = []
    for rid, d in all_runs(problem):
        if d["status"] != "open" or rid in skip:
            continue
        e = execution_record(problem, rid)
        if e and e.get("end"):
            lines.append("%s: worker exited %s — ingest it or `run.py void %s "
                         "--reason ...`" % (rid, e["end"], rid))
        elif e and e.get("breaches"):
            for b in e["breaches"]:
                lines.append("%s: over its %s budget since %s (%s %s seen, "
                             "limit %s) — Investigator decision: `kill %s`, "
                             "or let it run"
                             % (rid, b["kind"], b["at"], b["seen"], b["unit"],
                                b["limit"], e.get("pid")))
        else:
            age = (datetime.now(timezone.utc)
                   - datetime.strptime(d["ts"], "%Y-%m-%dT%H:%M:%SZ")
                   .replace(tzinfo=timezone.utc)).total_seconds()
            if age > 6 * 3600:
                lines.append("%s: open %dh with no worker exit on record — "
                             "investigate, or `run.py void %s --reason ...`"
                             % (rid, int(age // 3600), rid))
    if lines:
        print("Needs attention:")
        for l in lines:
            print("- " + l)


# ---------------------------------------------------------------- new

def cmd_new(args):
    problem = find_problem(args.problem)
    root = git_root(problem)
    tag = require_own_branch(root, "a dispatch")
    install_hook(root)
    ensure_gitignore(root)
    brief = Path(args.brief)
    if not brief.is_file():
        refuse("there is no brief at %s. Write one from templates/BRIEF.md and "
               "pass its path to --brief." % args.brief)
    text = brief.read_text()
    role = lab_config(root).get("roles", {}).get(args.role, {})
    model = args.model or role.get("model")
    duplicate_of = None
    if args.duplicates:
        if not RUN_ID.match(args.duplicates):
            refuse("--duplicates takes a run ID like R-030, not %r."
                   % args.duplicates)
        duplicate_of = find_run_anywhere(root, problem, args.duplicates)
        if duplicate_of is None:
            refuse("--duplicates names %s, and no branch this clone can see "
                   "holds a run by that ID. Run `run.py catchup` to fetch what "
                   "the others have pushed, then name a run that exists — a "
                   "duplicate pair nobody can look up teaches nothing."
                   % args.duplicates)
    if args.checks:
        if not RUN_ID.match(args.checks):
            refuse("--checks takes a run ID like R-030, not %r." % args.checks)
        if ingest_record(problem, args.checks) is None:
            refuse("--checks names %s, but there is no ingested run %s in this "
                   "problem. A referee checks a run that is on record."
                   % (args.checks, args.checks))
        checked_model = json.loads((run_dir(problem, args.checks) /
                                    "dispatch.json").read_text()).get("model")
        if checked_model == model and not args.accept_same_model:
            refuse("%s ran on %s, and this check would run on %s too. A model "
                   "checking its own kind of mistake is weak evidence, and the "
                   "ledger will refuse the promotion after the run is paid for "
                   "(claims.py does). Dispatch the check to a different model; "
                   "to proceed anyway, pass --accept-same-model."
                   % (args.checks, checked_model, model))
    if not model:
        refuse("this dispatch names no model. Pass --model, or add "
               "roles.%s.model to %s/lab.json. An unset model quietly inherits "
               "this session's model and spends an expensive one on a cheap "
               "job." % (args.role, root))
    if "available" in role or "unavailable" in role:
        refuse("roles.%s in lab.json carries a bare availability flag. A flag "
               "with no date goes stale — the quota resets and nobody flips it "
               "back. Use unavailable_until: \"YYYY-MM-DD\" with a note."
               % args.role)
    hold = role.get("unavailable_until")
    if hold:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(hold)):
            refuse("roles.%s.unavailable_until is %r; it must be a date like "
                   "2026-09-01." % (args.role, hold))
        if time.strftime("%Y-%m-%d", time.gmtime()) < hold:
            refuse("role %s is on hold until %s%s. A dispatch to a role that "
                   "cannot run is a run lost before it starts; pick another "
                   "role, or move the date in lab.json with the Investigator's "
                   "agreement." % (args.role, hold,
                                   ": " + role["note"] if role.get("note") else ""))
    if args.no_launch and role.get("command"):
        refuse("--no-launch is for roles that have no launch command — workers "
               "the Director hands the prompt to itself. Role %s launches "
               "through lab.json (%s); with --no-launch it would sit open with "
               "no worker, which is how a run once sat open with no worker. Drop "
               "--no-launch, or dispatch under a role with no command."
               % (args.role, role["command"]))

    limits = {"worker_timeout": args.worker_timeout or role.get("worker_timeout"),
              "memory_gb": args.memory_gb or role.get("memory_gb")}

    fp = fingerprint(text)
    for rid, d in all_runs(problem):
        if d.get("brief_fingerprint") == fp and d.get("status") == "open":
            if not args.force:
                refuse("%s is still open and carries this same brief. Ingest "
                       "or void it first, or say in this brief how the question "
                       "differs; dispatching the same question twice is usually "
                       "a lost thread or a retry that fired twice. If you mean "
                       "it, pass --force." % rid)
            print("Warning: %s is still open and carries the same brief; "
                  "dispatching anyway on --force." % rid)

    before, position = dirty(root), head(root)
    rid = allocate_run(problem, tag)
    rundir = run_dir(problem, rid)
    rundir_rel = rel(rundir, root)
    allowed = [rundir_rel]
    for a in args.allow or []:
        r = rel(Path(a), root)
        if r is None:
            refuse("--allow %s is outside this repository, and a fence that "
                   "points out of the lab cannot be checked. Name a path "
                   "inside %s." % (a, root))
        if r not in allowed:
            allowed.append(r)

    (rundir / "packet").mkdir(parents=True, exist_ok=True)
    (rundir / "BRIEF.md").write_text(text)
    extra = [a for a in allowed if a != rundir_rel]
    fence = ("You may create or modify files only in this directory (`%s`) — "
             "your own run directory, which is where you are running%s"
             % (rundir_rel,
                " — and these paths:\n\n%s"
                % "\n".join("- `%s`" % a for a in extra) if extra else "."))
    charter = CHARTER.format(rid=rid, timeout=args.timeout,
                             packet="%s/packet/" % rundir_rel, fence=fence)
    (rundir / "AGENTS.md").write_text(
        "# Worker charter\n\nThese rules bind this run. Nothing outside this "
        "directory does.\n\n" + charter)
    (rundir / "PROMPT.md").write_text(
        "# Run %s\n\n%s\n---\n\n# The brief\n\n%s\n" % (rid, charter, text.strip()))
    dispatch = {
        "run": rid, "ts": now(), "status": "open", "actor": args.actor or model,
        "model": model, "role": args.role, "brief": rel(brief, root) or str(brief),
        "brief_sha": hashlib.sha256(text.encode()).hexdigest(),
        "brief_fingerprint": fp,
        "claims_pasted": sorted(set(CLAIM_ID.findall(text)), key=id_key),
        "checks": args.checks, "duplicates": args.duplicates,
        "investigator": tag, "host": host(),
        "director_session": director_session(),
        "timeout": args.timeout, "git_head": position, "allowed": allowed,
        "limits": limits,
        # Already dirty before this dispatch, so the fence check at ingest
        # cannot blame the worker for it. The brief joins the list because
        # this dispatch commits it itself.
        "ignore": sorted(before | {rel(brief, root)} - {None}),
        "command": (role.get("command") or "").replace(
            "{prompt}", "%s/PROMPT.md" % rundir_rel) or None,
    }
    write_json(rundir / "dispatch.json", dispatch)
    commit(root, [rundir_rel, rel(brief, root), ".gitignore"],
           "%s dispatched to %s" % (rid, model))
    print("%s — model %s, timeout %ss, may write: %s"
          % (rid, model, args.timeout, ", ".join(allowed)))
    if duplicate_of:
        print("Recorded as a deliberate duplicate of %s (read from %s). "
              "Catchup names the pair until the original is closed."
              % (args.duplicates, duplicate_of))
    if role.get("note"):
        # The registry's word on this worker, read at the moment it matters.
        print("Role %s: %s" % (args.role, role["note"]))

    if args.no_launch:
        print("Prepared but not launched. Prompt: %s/PROMPT.md" % rundir_rel)
        return
    template = role.get("command")
    if not template:
        refuse("lab.json names no launch command for role %s, so I cannot "
               "start the worker. Add roles.%s.command with {prompt} where the "
               "prompt file goes, or prepare the run with --no-launch and "
               "start the worker yourself." % (args.role, args.role))
    line = template.replace("{prompt}", str((rundir / "PROMPT.md").resolve()))
    argv = shlex.split(line)
    exe = shutil.which(argv[0])
    if exe is None:
        refuse("the launch command starts with %r and nothing by that name is "
               "on PATH. The worker would die before it began — a launch that "
               "cannot start is a harness failure, not a run. Fix lab.json's "
               "command (absolute paths are safest) or install the tool, then "
               "dispatch again. %s is prepared; start it by hand or void it."
               % (argv[0], rid))
    argv[0] = exe
    log = rundir / "worker.log"
    execution = {"command": line, "executable": exe, "start": now(),
                 "run": rid, "limits": limits}
    write_json(rundir / "execution.json", execution)
    budget = ", ".join("%s %s" % (k, v) for k, v in limits.items() if v)
    print("Launching: %s\nWorker output (both streams) goes to %s/worker.log — "
          "`tail -f` it to watch.%s"
          % (line, rundir_rel, " Watching: %s." % budget if budget else ""))
    sys.stdout.flush()
    if args.detach:
        # The watcher lives on in its own session; `new` returns now so the
        # next dispatch is not queued behind this worker's whole lifetime.
        # execution.json gets pid at once, end/exit at the end.
        if os.fork():
            print("Detached. execution.json carries the pid now and the exit "
                  "when the worker finishes; ingest refuses until then. "
                  "Watcher output: %s/watcher.log" % rundir_rel)
            overdue_report(problem, skip={rid})
            return
        os.setsid()
        wfh = open(rundir / "watcher.log", "ab")
        os.dup2(wfh.fileno(), 1)
        os.dup2(wfh.fileno(), 2)
        os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
        try:
            launch_and_watch(argv, rundir, log, execution, limits, role, rid,
                             rundir_rel)
        finally:
            os._exit(0)
    launch_and_watch(argv, rundir, log, execution, limits, role, rid, rundir_rel)
    overdue_report(problem, skip={rid})


def launch_and_watch(argv, rundir, log, execution, limits, role, rid, rundir_rel):
    t0 = time.time()
    with open(log, "wb") as fh:           # a worker that dies at its API says
        proc = subprocess.Popen(argv, cwd=str(rundir),           # so only here
                                stdout=fh, stderr=subprocess.STDOUT)
        execution["pid"] = proc.pid
        write_json(rundir / "execution.json", execution)
        code = watch(proc, execution, rundir / "execution.json", t0, limits)
    execution.update(end=now(), exit=code,
                     wall_seconds=int(time.time() - t0))
    usage = extract_usage(log, role.get("usage_pattern"))
    if usage:
        execution["usage"] = usage
    write_json(rundir / "execution.json", execution)
    size = log.stat().st_size
    print("Worker exited %d after %ds, %d byte(s) in %s/worker.log.%s Ingest "
          "with `run.py ingest %s`."
          % (code, execution["wall_seconds"], size, rundir_rel,
             "" if size else " It printed nothing at all, which usually means "
             "it never really started — read the log before the packet.", rid))
    return code


# ---------------------------------------------------------------- ingest

def load_dispatch(problem, rid):
    p = run_dir(problem, rid) / "dispatch.json"
    if not p.exists():
        refuse("there is no run %s under %s/runs. Run `run.py catchup` to "
               "see which runs are on file." % (rid, problem.name))
    d = json.loads(p.read_text())
    if d.get("status") != "open":
        refuse("%s was already ingested on %s, with verdict %s. A run enters "
               "the record once. If the packet was wrong, dispatch a fresh "
               "run — packets are never repaired in place."
               % (rid, d.get("ingested_at"), d.get("verdict")))
    return d


def strings(ret, key, rid):
    v = ret.get(key)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        refuse("RETURN.json in %s has %s as %r. It must be a list of strings. "
               "Recovery is a fresh dispatch, or `run.py ingest %s "
               "--record-broken` to file the packet as it stands."
               % (rid, key, v, rid))
    return v


def read_packet(problem, rid, d):
    """Every gate between a returned packet and the record."""
    packet = run_dir(problem, rid) / "packet"
    result, ret_path = packet / "RESULT.md", packet / "RETURN.json"
    tail = ("Recovery is a fresh dispatch, or `run.py ingest %s "
            "--record-broken` to file the packet as it stands under verdict "
            "UNINGESTABLE." % rid)
    if not result.exists():
        refuse("%s returned no RESULT.md — I looked in %s. If the worker never "
               "wrote one, dispatch again. %s" % (rid, packet, tail))
    text = result.read_text()
    first = next((l for l in text.splitlines() if l.strip()), "")
    m = VERDICT_LINE.match(first.strip())
    if not m:
        if "PENDING" in first:
            refuse("RESULT.md in %s still says PENDING — the worker never "
                   "finished. The partial sections it wrote are preserved; "
                   "file the run with `run.py ingest %s --record-broken`, or "
                   "re-dispatch." % (rid, rid))
        refuse("the first line of %s/packet/RESULT.md is %r. It must be exactly "
               "`# VERDICT: PASS`, `# VERDICT: FAIL` or `# VERDICT: UNDECIDED`. "
               "%s" % (rid, first.strip(), tail))
    secs = split_sections(text)
    missing = [s for s in SECTIONS if not secs.get(s.lower())]
    if missing:
        refuse("RESULT.md in %s has nothing under: %s. All four of `## What was "
               "done`, `## Not claimed`, `## Leads` and `## Validation` must be "
               "present and say something — \"None.\" is an acceptable answer "
               "for Leads, an empty section is not. %s"
               % (rid, ", ".join(missing), tail))
    if not ret_path.exists():
        refuse("%s returned no RETURN.json — I looked in %s. Both packet files "
               "are required. %s" % (rid, packet, tail))
    try:
        ret = json.loads(ret_path.read_text())
    except json.JSONDecodeError as e:
        refuse("RETURN.json in %s is not valid JSON: %s. It must be plain JSON "
               "with no comments and no trailing commas. %s" % (rid, e, tail))
    if not isinstance(ret, dict):
        refuse("RETURN.json in %s is not a JSON object. %s" % (rid, tail))
    absent = [k for k in REQUIRED if k not in ret]
    if absent:
        refuse("RETURN.json in %s has no %s. Every field in "
               "templates/RETURN.json is required. %s"
               % (rid, ", ".join(absent), tail))
    if "actor" in ret:
        refuse("RETURN.json in %s names an actor. Workers never name "
               "themselves — ingest stamps the actor from dispatch.json, which "
               "is what stops a run grading its own homework. %s" % (rid, tail))
    if ret["validation"] not in ("replay", "review"):
        refuse("RETURN.json in %s says validation is %r. It must be `replay` (a "
               "machine can re-run this) or `review` (a referee must check it "
               "by hand). %s" % (rid, ret["validation"], tail))
    for key in ("exits", "machine_markers", "claims_used", "claims_proposed"):
        strings(ret, key, rid)
    for s in ret["claims_proposed"]:
        hit = CLAIM_ID.search(s)
        if hit:
            refuse("claims_proposed in %s contains the claim ID %s: %r. "
                   "Proposed claims are plain statements — workers never mint "
                   "IDs, and ingest allocates one for each statement it files. "
                   "%s" % (rid, hit.group(0), s, tail))
    stray = [c for c in ret["claims_used"] if c not in d["claims_pasted"]]
    if stray:
        refuse("claims_used in %s names %s, which this dispatch never pasted "
               "into the brief. A worker may use only the claims it was given: "
               "%s. %s" % (rid, ", ".join(stray),
                           ", ".join(d["claims_pasted"]) or "none", tail))
    return m.group(1), secs, ret


def replay_command(validation_text):
    """The first fenced or indented code block, whole. The gate once ran only
    the first line of a three-line block and passed on nothing."""
    m = FENCE.search(validation_text)
    if m:
        block = m.group(1)
    else:
        m = INDENTED.search(validation_text)
        if not m:
            return None
        block_lines = []
        for line in validation_text[m.start():].splitlines():
            hit = INDENTED.match(line)
            if not hit:
                break
            block_lines.append(hit.group(1))
        block = "\n".join(block_lines)
    block = "\n".join(l.rstrip() for l in block.splitlines() if l.strip())
    return block or None


def do_replay(rundir, secs, ret, rid, timeout):
    """Returns (replayed, warnings, replay record). Nonzero exit fails
    whatever was printed; markers must appear character for character. A
    passing replay proves the command ran and printed the declared strings —
    what it recomputed is a question for a referee, not for this check."""
    if ret["validation"] == "review":
        return False, ["validation is a review; no referee run has checked "
                       "this yet"], None
    cmd = replay_command(secs["validation"])
    if not cmd:
        refuse("%s declares validation `replay` but its `## Validation` section "
               "holds no command — I look for the first indented or fenced code "
               "block there. Recovery is a fresh dispatch, or `run.py ingest %s "
               "--record-broken`." % (rid, rid))
    record = {"command": cmd, "timeout": timeout}
    try:
        # One sh script under set -e: a failing line fails the replay even
        # when a later line exits clean.
        r = subprocess.run("set -e\n" + cmd, shell=True, cwd=str(rundir),
                           capture_output=True, text=True, timeout=timeout)
        out, code = r.stdout + r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        record["exit"] = None
        return False, ["the replay did not finish inside the %ss timeout "
                       "this dispatch set" % timeout], record
    record["exit"] = code
    missing = [m for m in ret["machine_markers"] if m not in out]
    if code != 0:
        return False, ["the replay exited %d; a nonzero exit fails whatever "
                       "was printed" % code], record
    if missing:
        return False, ["the replay never printed %s, and markers are matched "
                       "character for character, never by pattern"
                       % ", ".join(repr(m) for m in missing)], record
    return True, [], record


def allocate_claim(problem, statement, actor):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        claims.main(["new", "--statement", statement, "--actor", actor,
                     "--problem", str(problem)])
    return claims.first_id(buf.getvalue())


def similar(first, second):
    """Two statements that look like the same claim. Crude on purpose:
    normalized word overlap. It warns, it never blocks — only a reader can
    tell two claims apart."""
    def toks(s):
        return set(re.findall(r"[a-z0-9]+", s.lower())) - STOP
    a, b = toks(first), toks(second)
    return bool(a and b) and len(a & b) / float(len(a | b)) >= 0.6


def near_duplicates(problem, statement):
    """Every claim on file that looks like this statement — across every
    investigator's stream, since the same idea proposed twice in two labs is
    the pair nobody catches."""
    known, order = claims.load(problem)
    return [cid for cid in order if similar(statement, known[cid]["statement"])]


def apply_reviews(problem, rid, ret, verdict, actor):
    """A referee run names the run it checked in RETURN.json `reviewed`.
    Replay and review are separate facts, never a ladder: the review is
    recorded in the target's `reviewed_by` and rewrites nothing else."""
    notes, touched = [], []
    for target in ret.get("reviewed") or []:
        prev = ingest_record(problem, target) if RUN_ID.match(str(target)) else None
        if prev is None:
            refuse("RETURN.json says this run reviewed %s, but there is no "
                   "ingested run %s here. Name a run this lab ingested, or drop "
                   "the field." % (target, target))
        if verdict != "PASS":
            notes.append("%s records no review: a review counts only when the "
                         "referee returns PASS." % target)
            continue
        if prev["actor"].strip().casefold() == actor.strip().casefold():
            refuse("%s was run by %s and so was this one. A review by the same "
                   "actor validates nothing — dispatch a referee with a "
                   "different actor." % (target, prev["actor"]))
        prev["reviewed_by"] = sorted(set(prev.get("reviewed_by") or []) | {rid})
        notes.append("%s reviewed by %s." % (target, rid))
        write_json(run_dir(problem, target) / "ingest.json", prev)
        touched.append(target)
    return notes, touched


def cmd_ingest(args):
    problem = find_problem(args.problem)
    root = git_root(problem)
    rid, rundir = args.run, run_dir(problem, args.run)
    d = load_dispatch(problem, rid)
    tag = require_owner(problem, root, rid, "ingesting a run")
    actor = d["actor"]

    if args.record_broken:
        packet = rundir / "packet"
        has_packet = (packet / "RESULT.md").exists() or \
                     (packet / "RETURN.json").exists()
        verdict = "UNINGESTABLE" if has_packet else "HARNESS-FAILURE"
        reasons = []
        refusal = rundir / "refusal.txt"
        if refusal.exists():
            reasons.append(refusal.read_text().strip())
        e = execution_record(problem, rid)
        if e:
            if e.get("exit") not in (0, None):
                reasons.append("worker exited %s" % e["exit"])
            elif not e.get("end"):
                reasons.append("no worker exit on record")
        if args.reason:
            reasons.insert(0, args.reason.strip())
        if not reasons:
            refuse("nothing on record says why %s failed: no refusal.txt, no "
                   "worker exit. Pass --reason with what happened — a failure "
                   "filed as \"no reason recorded\" is the failure nobody can "
                   "learn from." % rid)
        # A refusal never silently destroys a lead: quote what the packet
        # proposed, provenance-marked, allocating nothing.
        salvage = []
        try:
            ret = json.loads((packet / "RETURN.json").read_text())
            for p in ret.get("claims_proposed") or []:
                if isinstance(p, str):
                    salvage.append("proposed (untrusted, no ID): %s" % p)
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
        try:
            secs = split_sections((packet / "RESULT.md").read_text())
            if secs.get("leads"):
                salvage.append("Leads (untrusted):\n\n%s" % secs["leads"])
        except OSError:
            pass
        d.update(status=verdict.lower(), verdict=verdict, ingested_at=now())
        write_json(rundir / "dispatch.json", d)
        # The transcript matters most exactly here: a run filed broken is
        # the one whose "what happened" nobody can reconstruct later.
        write_json(rundir / "ingest.json",
                   {"run": rid, "ts": now(), "actor": actor,
                    "investigator": tag, "host": host(),
                    "transcript": attach_transcript(problem, root, rid, d,
                                                    args.transcript),
                    "verdict": verdict, "replayed": False,
                    "validation": None,
                    "headline": "filed without ingest: " + reasons[0],
                    "claims": [], "refused_for": reasons,
                    "warnings": ["filed with --record-broken: nothing in this "
                                 "packet is on record"]})
        headline = ("%s never produced a packet" % rid if verdict ==
                    "HARNESS-FAILURE" else
                    "%s returned a packet that could not be ingested" % rid)
        body = ["**Run:** %s · **Actor:** %s · **Verdict:** %s"
                % (rid, actor, verdict), "",
                "## Why", ""] + ["- " + r for r in reasons]
        if salvage:
            body += ["", "## Salvaged from the packet (not on record)", ""]
            body += ["- " + x if not x.startswith("Leads") else "\n" + x
                     for x in salvage]
        body += ["", "Nothing here counts as evidence. Packets are never "
                 "hand-edited; recovery is a fresh dispatch."]
        res = resource_line(problem, rid)
        if res:
            body += ["", "**Resources:** " + res]
        entry = file_entry(problem, headline,
                           "%s | %s | %s | %s"
                           % (time.strftime("%Y-%m-%d", time.gmtime()), rid,
                              verdict, reasons[0][:80]),
                           "\n".join(body), tag)
        commit(root, [rel(rundir, root), rel(problem / "notebook", root)],
               "%s %s: %s" % (rid, verdict, reasons[0][:60]))
        print("%s filed as %s (%s). No claims allocated. Entry: %s"
              % (rid, verdict, reasons[0][:80], rel(entry, root)))
        push_own_branch(root, tag)
        overdue_report(problem, skip={rid})
        return

    e = execution_record(problem, rid)
    if e and e.get("pid") and not e.get("end") and pid_alive(e["pid"]):
        refuse("%s's worker (pid %s) is still running. Ingesting a live run "
               "lets the worker keep writing into an already-filed packet — "
               "the mutation this lab has been burned by. Wait for it, or "
               "kill it: `kill %s`. --worker-done does not override a live "
               "process; it covers a worker that has exited without "
               "execution.json saying so." % (rid, e["pid"], e["pid"]))

    try:
        verdict, secs, ret = read_packet(problem, rid, d)

        # The fence judges only what this worker could have written:
        # uncommitted files outside its allowed paths, excluding every other
        # run's directory. Committed history is never consulted, so nothing
        # the Director or a sibling run commits can implicate this worker.
        # Any run directory of any problem is another worker's territory,
        # not this one's: several problems ran workers at once in one lab,
        # and live workers elsewhere were blamed on the run under ingest.
        own = (rel(problem / "runs", root) or "runs") + "/" + rid + "/"
        any_run = re.compile(r"^(?:.*/)?runs/[^/]+/")
        changed = dirty(root) - set(d.get("ignore") or [])
        changed = {p for p in changed
                   if not (any_run.match(p) and not p.startswith(own))
                   and "__pycache__" not in p and not p.endswith(".pyc")}
        bad = outside(changed, d["allowed"])
        if bad:
            refuse("%s wrote outside its fence: %s. It was allowed %s and "
                   "nothing else. The run is not filed. Recovery is a fresh "
                   "dispatch with the fence stated in the brief, or `run.py "
                   "ingest %s --record-broken` to file it as it stands."
                   % (rid, ", ".join(bad), ", ".join(d["allowed"]), rid))

        replayed, warnings, replay = do_replay(rundir, secs, ret, rid,
                                               d["timeout"])
        if args.reviewed:
            override = [x.strip() for chunk in args.reviewed
                        for x in chunk.split(",") if x.strip()]
            warnings.append("reviewed set by the Director at ingest: %s "
                            "(the packet said %s)."
                            % (", ".join(override),
                               ", ".join(ret.get("reviewed") or []) or "nothing"))
            ret["reviewed"] = override
        elif not ret.get("reviewed") and d.get("checks"):
            ret["reviewed"] = [d["checks"]]
            warnings.append("reviewed filled from the dispatch: this run was "
                            "dispatched as a check of %s." % d["checks"])
        notes, touched = apply_reviews(problem, rid, ret, verdict, actor)
    except SystemExit:
        msg = claims.LAST_REFUSAL.get("message")
        if msg:
            (rundir / "refusal.txt").write_text(msg + "\n")
        raise

    allocated = []
    for statement in ret["claims_proposed"]:
        dupes = near_duplicates(problem, statement)
        cid = allocate_claim(problem, statement, actor)
        allocated.append((cid, statement))
        if dupes:
            warnings.append("%s looks close to %s already on file — read them "
                            "side by side before either is promoted"
                            % (cid, ", ".join(dupes)))

    body = ["**Run:** %s · **Actor:** %s · **Model:** %s · **Verdict:** %s"
            % (rid, actor, d["model"], verdict),
            "**Replayed:** %s%s" % ("yes" if replayed else "no",
                                    "" if replayed and not warnings
                                    else " — " + "; ".join(warnings)
                                    if warnings else ""),
            "**Validation:** %s%s" % (ret["validation"],
                                      " — `%s`" % replay["command"].replace("\n", "` then `")
                                      if replay else ""),
            "", "## Headline", "", ret["headline"], "", "## Markers checked", ""]
    body += ["- `%s`" % m for m in ret["machine_markers"]] or ["- None declared."]
    body += ["", "## Claims allocated", ""]
    body += ["- %s — %s" % (c, s) for c, s in allocated] or ["- None."]
    if notes:
        body += ["", "## Reviews", ""] + ["- " + n for n in notes]
    body += ["", "## Leads", "", secs["leads"], "", "## Packet", "",
             "`%s/packet/RESULT.md` · `%s/packet/RETURN.json`"
             % (rel(rundir, root), rel(rundir, root))]
    res = resource_line(problem, rid)
    if res:
        body += ["", "**Resources:** " + res]
    entry = file_entry(problem, ret["headline"],
                       "%s | %s | %s | %s" % (time.strftime("%Y-%m-%d", time.gmtime()),
                                              rid, verdict, ret["headline"]),
                       "\n".join(body), tag)

    record = {"run": rid, "ts": now(), "actor": actor, "verdict": verdict,
              "investigator": tag, "host": host(),
              "transcript": attach_transcript(problem, root, rid, d,
                                              args.transcript),
              "director_session": director_session(),
              "headline": ret["headline"], "replayed": replayed,
              "reviewed_by": [],
              "validation": ret["validation"], "replay": replay,
              "claims": [c for c, _ in allocated], "warnings": warnings,
              "entry": rel(entry, root), "reviewed": ret.get("reviewed") or []}
    write_json(rundir / "ingest.json", record)
    d.update(status="ingested", verdict=verdict, ingested_at=record["ts"],
             replayed=replayed)
    write_json(rundir / "dispatch.json", d)
    paths = [rel(rundir, root), rel(problem / "notebook", root)]
    paths += [rel(run_dir(problem, t), root) for t in touched]
    with ingest_lock(root):
        commit(root, paths, "%s ingested: %s — %s" % (rid, verdict, ret["headline"]))

    print("%s %s (replayed: %s)" % (rid, verdict, "yes" if replayed else "no"))
    for w in warnings + notes:
        print("- " + w)
    for cid, s in allocated:
        print("- %s proposed: %s" % (cid, claims.one_line(s)))
    print("Entry: %s" % rel(entry, root))
    push_own_branch(root, tag)
    overdue_report(problem, skip={rid})
    status_report(problem)
    rotation_notice(problem, root)


# ---------------------------------------------------------------- note

def cmd_note(args):
    problem = find_problem(args.problem)
    root = git_root(problem)
    tag = require_own_branch(root, "a notebook entry")
    actor = claims.resolve_actor(args.actor, tag)
    body = Path(args.body_file).read_text() if args.body_file else (args.body or "")
    if not body.strip():
        refuse("a note needs a body: pass --body with the text or --body-file "
               "with a path. A headline with nothing under it tells a later "
               "reader nothing.")
    entry = file_entry(problem, args.headline,
                       "%s | note | — | %s" % (time.strftime("%Y-%m-%d", time.gmtime()),
                                               args.headline),
                       "**Actor:** %s · **Kind:** Director note (no packet, no "
                       "claims)\n\n%s" % (actor, body.strip()), tag)
    commit(root, [rel(problem / "notebook", root)], "note: %s" % args.headline)
    print("Entry: %s" % rel(entry, root))
    push_own_branch(root, tag)


# ---------------------------------------------------------------- catchup

def describe_event(rec):
    """One ledger event in a line, whichever stream it came from."""
    if rec["event"] == "new":
        return "%s stated as %s by %s" % (rec["id"], rec["status"], rec["actor"])
    return "%s %s -> %s by %s%s" % (rec["id"], rec["from"], rec["to"],
                                    rec["actor"],
                                    " (%s)" % rec["evidence"]
                                    if rec.get("evidence") else "")


def hours_since(stamp):
    """Hours since an ISO timestamp, or None when it cannot be read."""
    try:
        then = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600.0


def others_report(root, problem, since):
    """What the other investigators have recorded, read straight from their
    branches. Without it "whose run is this, and is it alive" is a question
    the record cannot answer, and two labs quietly hold two truths about one
    claim until the paper is written."""
    mine = own_tag(root) if joined(root) else None
    fetch(root)
    base = problem_rel(root, problem)
    hours = ((lab_config(root).get("machine") or {}).get("open_run_hours") or 24)
    print("\nOther investigators (read from their branches, not merged):")
    seen = False
    for tag, ref in branch_refs(root, skip=mine):
        seen = True
        lines = []
        for rid in sorted(list_branch_dir(root, ref, base + "runs"), key=id_key):
            d = read_branch_json(root, ref, base + "runs/%s/dispatch.json" % rid)
            if not d:
                continue
            ing = read_branch_json(root, ref, base + "runs/%s/ingest.json" % rid)
            if ing and ing["ts"] >= since:
                lines.append("%s %s — %s" % (rid, ing["verdict"], ing["headline"]))
            elif d.get("status") == "open":
                age = hours_since(d.get("ts"))
                if age is not None and age > hours:
                    lines.append("%s open %dh (%s)" % (rid, age, d.get("model")))
            elif d["ts"] >= since:
                lines.append("%s dispatched to %s" % (rid, d.get("model")))
        for name in list_branch_dir(root, ref, base + "claims"):
            if not (name.startswith("ledger") and name.endswith(".jsonl")):
                continue
            for line in (read_branch_file(root, ref,
                                          base + "claims/" + name) or "").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    if rec["ts"] >= since:
                        lines.append(describe_event(rec))
        print("  %s (%s):" % (tag, ref))
        print("\n".join("    " + l for l in lines) if lines
              else "    nothing since %s" % since)
    if not seen:
        print("  nobody else has pushed a branch this clone can see")
    n = unpushed(root, mine)
    if n is None:
        print("  yours: no remote — nothing you record here reaches anyone else")
    else:
        print("  yours: unpushed %d" % n)


def duplicate_pairs(root, problem):
    """Deliberate duplicates whose original is still open — the pair that
    was meant to be a second opinion and is now two people doing one job."""
    out = []
    for rid, d in all_runs(problem):
        target = d.get("duplicates")
        if not target:
            continue
        other = run_record_anywhere(root, problem, target)
        if other is None or other.get("status") == "open":
            out.append("%s duplicates %s, which is still open (%s)"
                       % (rid, target, id_tag(target) or "founding stream"))
    return out


def default_since(root):
    """Where catchup starts when nobody says: the last meeting, because that
    is the line the group drew under what it had read, and a week otherwise.
    A session that opens by asking the Director to pick a date starts by
    getting it wrong."""
    sha, when = last_meeting(root)
    if when:
        return "the last meeting (%s)" % sha[:8], when
    week = datetime.now(timezone.utc) - timedelta(days=7)
    return "the last seven days", week.strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_catchup(args):
    problem = find_problem(args.problem)
    root = git_root(problem)
    since = args.since
    if not since:
        since, cutoff = default_since(root)
    elif re.match(r"^\d{4}-\d{2}-\d{2}$", since):
        cutoff = since + "T00:00:00Z"
    else:
        cutoff = commit_time(root, since)
        if cutoff is None:
            refuse("%s is neither a commit this repository knows nor a date "
                   "like 2026-08-19. Pass one of those." % since)
    print("Since %s (%s):" % (since, cutoff))

    lines = []
    for rid, d in all_runs(problem):
        if d["ts"] >= cutoff:
            lines.append("%s dispatched to %s" % (rid, d["model"]))
        ing = ingest_record(problem, rid)
        if ing and ing["ts"] >= cutoff:
            tags = []
            if ing.get("replayed"):
                tags.append("replayed")
            if ing.get("reviewed_by"):
                tags.append("reviewed by %s" % ",".join(ing["reviewed_by"]))
            lines.append("%s %s (%s) — %s"
                         % (rid, ing["verdict"], "; ".join(tags) or "unchecked",
                            ing["headline"]))
    print("\nRuns:")
    print("\n".join("  " + l for l in lines) if lines else "  nothing")

    moves = [describe_event(rec)
             for rec, _ in sorted(claims.stream_events(problem),
                                  key=lambda e: e[0]["ts"])
             if rec["ts"] >= cutoff]
    print("\nClaims:")
    print("\n".join("  " + m for m in moves) if moves else "  nothing")

    open_runs = ["%s (%s, dispatched %s)" % (rid, d["model"], d["ts"])
                 for rid, d in all_runs(problem) if d["status"] == "open"]
    print("\nStill open:")
    print("\n".join("  " + o for o in open_runs) if open_runs else "  nothing")
    if joined(root):
        others_report(root, problem, last_meeting(root)[1] or cutoff)
    overdue_report(problem)
    if install_hook(root) is None:
        print("\nThe pre-commit guard is not installed in this clone (another "
              "hook is in its place). Hand commits can sweep open runs into "
              "the history; merge the lab's hook in.")

    status_report(problem)
    baseline_report(problem, root)
    catchup_lints(problem, root)


BASELINE_LINE = re.compile(r"baseline.*?fetched\s+(\d{4}-\d{2}-\d{2})", re.I)


def baseline_report(problem, root):
    """Baselines in sources/MANIFEST.md carry their fetch date; the old ones
    are named for a re-fetch. A public board updated under one lab
    while its baseline stood still."""
    manifest = problem / "sources" / "MANIFEST.md"
    if not manifest.exists():
        return
    days = (lab_config(root).get("sources") or {}).get("refetch_days") or 30
    today = datetime.now(timezone.utc).date()
    stale = []
    for line in manifest.read_text().splitlines():
        m = BASELINE_LINE.search(line)
        if not m:
            continue
        age = (today - datetime.strptime(m.group(1), "%Y-%m-%d").date()).days
        if age > days:
            stale.append((age, line.strip()))
    if stale:
        print("\nBaselines older than %d days — re-fetch and re-score, or a "
              "\"record\" here may already be beaten:" % days)
        for age, line in stale:
            print("- %dd: %s" % (age, line[:110]))


STATUS_LINTED = ("Bottom line", "What is settled")


def status_report(problem):
    """What git and the ledger know about STATUS.md, surfaced for the
    Director to act on by hand — nothing here rewrites the page. Two
    failures: a header naming a run twenty-eight runs stale,
    and a proposed claim written in the voice of fact and refuted thirty
    minutes later, eight times."""
    root = git_root(problem)
    path = problem / "STATUS.md"
    stamp = git(root, "log", "-1", "--format=%ct", "--", str(path)).stdout.strip()
    if not stamp:
        print("\nSTATUS.md has never been committed, so everything above is "
              "missing from it.")
    else:
        cut = datetime.fromtimestamp(int(stamp), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        since = [rid for rid, _ in all_runs(problem)
                 if (ingest_record(problem, rid) or {}).get("ts", "") >= cut]
        print("\nSTATUS.md last committed %s; %d run(s) ingested since%s."
              % (cut, len(since),
                 ": " + ", ".join(since[:6]) + (", …" if len(since) > 6 else "")
                 if since else ""))
    if not path.exists():
        return
    known, _ = claims.load(problem)
    section, flagged = None, []
    for line in path.read_text().splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if section not in STATUS_LINTED:
            continue
        for cid in CLAIM_ID.findall(line):
            if (known.get(cid, {}).get("status") == "proposed"
                    and not re.search(re.escape(cid) + r"\s*\(proposed", line)):
                flagged.append((cid, section, line.strip()))
    if flagged:
        print("STATUS.md states as settled what is only proposed — label it "
              "\"C-NNN (proposed, unreviewed)\" by hand, or take it out:")
        for cid, section, line in flagged:
            print("- %s in \"%s\": %s" % (cid, section, line[:110]))


def catchup_lints(problem, root=None):
    """The standing lints, printed with every catchup so orientation and
    housekeeping are one report. Every line here is closable — an unclosable
    flag teaches its reader to skim — and the chronic are aggregated, never
    listed one per line."""
    root = root or git_root(problem)
    known, order = claims.load(problem)
    runs = all_runs(problem)
    print("\nAttention:")
    lines = []

    pairs = duplicate_pairs(root, problem)
    if pairs:
        lines.append("%d deliberate duplicate(s) whose original is still open "
                     "— ingest or void the original, or void the duplicate:"
                     % len(pairs))
        lines += ["  " + p for p in pairs]

    owed = []
    for rid, d in runs:
        ing = ingest_record(problem, rid)
        if (ing and ing.get("validation") == "review"
                and not ing.get("reviewed_by")
                and not ing.get("review_waived")
                and ing.get("verdict") in ("PASS", "FAIL", "UNDECIDED")):
            owed.append(rid)
    if owed:
        lines.append("%d run(s) owe a review (oldest %s) — dispatch a referee "
                     "whose RETURN.json lists the run in `reviewed`, or "
                     "`run.py waive-review <run> --reason ...`"
                     % (len(owed), owed[0]))

    dupes = []
    for rid, d in runs:
        ing = ingest_record(problem, rid)
        for w in (ing or {}).get("warnings") or []:
            m = re.match(r"(\S+) looks close to", w)
            if m and known.get(m.group(1), {}).get("status") == "proposed":
                dupes.append("%s (%s): %s" % (m.group(1), rid, w))
    if dupes:
        lines.append("%d duplicate warning(s) unresolved — promote, supersede "
                     "or refute the claim to clear each:" % len(dupes))
        lines += ["  " + x for x in dupes[:8]]
        if len(dupes) > 8:
            lines.append("  ... and %d more" % (len(dupes) - 8))

    thin = []
    for rid, d in runs:
        ing = ingest_record(problem, rid)
        if not ing or not transcript_setting(root, d.get("role")).get("glob"):
            continue
        t = ing.get("transcript")
        if t is None or not t.get("stored"):
            thin.append(rid)
    if thin:
        lines.append("%d ingested run(s) have no transcript stored, though "
                     "their role says where to find one — `run.py transcript "
                     "<run>` attaches it (raise transcripts.max_mb first if it "
                     "was too big): %s"
                     % (len(thin), ", ".join(thin[:8])
                        + (", …" if len(thin) > 8 else "")))

    shaky = []
    for cid in order:
        c = known[cid]
        if c["status"] != "verified":
            continue
        for r in c.get("rests_on") or []:
            st = known.get(r, {}).get("status", "missing")
            if st != "verified":
                shaky.append("%s rests on %s [%s]" % (cid, r, st))
    if shaky:
        lines.append("%d verified claim(s) rest on something not verified:"
                     % len(shaky))
        lines += ["  " + x for x in shaky[:8]]

    accepted = [cid for cid in order
                if known[cid]["status"] == "accepted-by-investigator"]
    if accepted:
        lines.append("accepted on the Investigator's word, not proved: %s"
                     % ", ".join(accepted))

    weak = [cid for cid in order
            if known[cid]["status"] == "verified"
            and str(known[cid].get("independence") or "").startswith("none")]
    if weak:
        lines.append("verified with no model independence (candidates for a "
                     "stronger referee): %s" % ", ".join(weak))

    if lines:
        for l in lines:
            print("  " + l)
    else:
        print("  nothing")

    # Per-model totals: runs, ingested, refused, wall time, tokens.
    per = {}
    for rid, d in runs:
        m = d.get("model") or "?"
        row = per.setdefault(m, {"runs": 0, "ingested": 0, "refused": 0,
                                 "wall": 0, "tokens": ""})
        row["runs"] += 1
        if d.get("status") == "ingested":
            row["ingested"] += 1
        elif d.get("status") in ("uningestable", "harness-failure"):
            row["refused"] += 1
        e = execution_record(problem, rid)
        if e and e.get("wall_seconds"):
            row["wall"] += e["wall_seconds"]
    if per:
        print("\nPer model:")
        for m in sorted(per):
            r = per[m]
            print("  %-40s %3d run(s), %d ingested, %d refused, %dm wall"
                  % (m, r["runs"], r["ingested"], r["refused"],
                     r["wall"] // 60))
    # Roles on hold: a hold that is wrong is seen here daily, not found at
    # dispatch.
    today = time.strftime("%Y-%m-%d", time.gmtime())
    held = [(name, r) for name, r in
            (lab_config(git_root(problem)).get("roles") or {}).items()
            if str(r.get("unavailable_until") or "") > today]
    if held:
        print("\nRoles on hold:")
        for name, r in held:
            print("  %s until %s%s" % (name, r["unavailable_until"],
                                       ": " + r["note"] if r.get("note") else ""))


# ------------------------------------------------------- void, lint, waive

def cmd_void(args):
    """Close a run that produced nothing. Not for packets — those are filed
    with --record-broken — but for the run that never launched, the worker
    that died silent, the dispatch a fresh run superseded."""
    problem = find_problem(args.problem)
    root = git_root(problem)
    rid = args.run
    d = load_dispatch(problem, rid)
    tag = require_owner(problem, root, rid, "voiding a run")
    packet = run_dir(problem, rid) / "packet"
    if (packet / "RESULT.md").exists() or (packet / "RETURN.json").exists():
        refuse("%s has a packet. Ingest it, or file it with `run.py ingest %s "
               "--record-broken` — void is only for runs that produced "
               "nothing." % (rid, rid))
    d.update(status="void", verdict="VOID", ingested_at=now(),
             void_reason=args.reason)
    write_json(run_dir(problem, rid) / "dispatch.json", d)
    entry = file_entry(problem, "%s voided: %s" % (rid, args.reason),
                       "%s | %s | VOID | %s"
                       % (time.strftime("%Y-%m-%d", time.gmtime()), rid,
                          args.reason[:80]),
                       "**Run:** %s · **Verdict:** VOID\n\n%s\n\nNo packet "
                       "was produced and no claims were allocated."
                       % (rid, args.reason), tag)
    commit(root, [rel(run_dir(problem, rid), root),
                  rel(problem / "notebook", root)],
           "%s VOID: %s" % (rid, args.reason[:60]))
    print("%s voided. Entry: %s" % (rid, rel(entry, root)))
    push_own_branch(root, tag)


def cmd_transcript(args):
    """Attach a worker's transcript to a run already on record. Discovery
    runs at ingest, when the session file is freshest, but a rule that was
    wrong then — or a store that was still writing — would otherwise mean
    the reasoning behind a filed run is lost for good. The packet is never
    touched: this adds what the worker's own command wrote beside it."""
    problem = find_problem(args.problem)
    root = git_root(problem)
    rid = args.run
    rec = ingest_record(problem, rid)
    if rec is None:
        refuse("%s has no ingest record, so there is nothing to attach a "
               "transcript to yet. Ingest or file the run first; ingest looks "
               "for the transcript itself." % rid)
    tag = require_owner(problem, root, rid, "attaching a transcript")
    stored = run_dir(problem, rid) / TRANSCRIPT_NAME
    if stored.exists() and not args.replace:
        refuse("%s already has a transcript on record (%s). A record is added "
               "to, not overwritten; if the stored copy is the wrong session, "
               "say `--replace` and the swap is in the history." % (rid, stored))
    d = load_json(run_dir(problem, rid) / "dispatch.json") or {}
    found = attach_transcript(problem, root, rid, d, args.path)
    if found is None:
        print("Nothing attached to %s: no session file was found for it. Name "
              "one with `--path`, or check roles.%s.transcript in lab.json."
              % (rid, d.get("role")))
        return
    rec["transcript"] = found
    write_json(run_dir(problem, rid) / "ingest.json", rec)
    commit(root, [rel(run_dir(problem, rid), root)],
           "%s: transcript attached" % rid)
    print("%s: transcript on record." % rid)
    push_own_branch(root, tag)


def cmd_lint(args):
    """Read-only packet contract check. Workers run it before finishing;
    anyone may run it any time. Prints what is wrong, changes nothing."""
    problem = find_problem(args.problem)
    rid = args.run
    p = run_dir(problem, rid) / "dispatch.json"
    if not p.exists():
        refuse("there is no run %s under %s/runs." % (rid, problem.name))
    d = json.loads(p.read_text())
    stored = run_dir(problem, rid) / TRANSCRIPT_NAME
    print("Transcript: %s" % ("%s, %d bytes gzipped"
                              % (TRANSCRIPT_NAME, stored.stat().st_size)
                              if stored.exists() else
                              "none on record yet; ingest looks for one"))
    packet = run_dir(problem, rid) / "packet"
    first = ""
    result = packet / "RESULT.md"
    if result.exists():
        first = next((l for l in result.read_text().splitlines()
                      if l.strip()), "")
    if "PENDING" in first:
        print("RESULT.md is still PENDING — the worker has not finished. "
              "The contract below applies to the finished packet.")
    try:
        verdict, secs, ret = read_packet(problem, rid, d)
        if ret["validation"] == "replay" and not replay_command(secs["validation"]):
            print("The packet does not pass the contract yet: validation "
                  "declares `replay` but `## Validation` holds no command — "
                  "the first indented or fenced code block there is what "
                  "ingest runs.")
            return
    except SystemExit:
        print("The packet does not pass the contract yet (reason above).")
        return
    print("%s: packet passes the contract." % rid)


def cmd_waive_review(args):
    """An owed review that will not happen, with the reason on record. This
    is what clears the 'reviews owed' line in catchup — an unclosable flag
    teaches its reader to skim, which is how an owed referee stayed flagged
    for three days and was never dispatched."""
    problem = find_problem(args.problem)
    root = git_root(problem)
    rid = args.run
    rec = ingest_record(problem, rid)
    if rec is None:
        refuse("%s has no ingest record, so there is no review to waive." % rid)
    tag = require_owner(problem, root, rid, "waiving a review")
    rec["review_waived"] = args.reason
    # Never demanded here: waiving needs no signature the lab does not
    # already have, and a flag that refuses on a lab nobody has joined would
    # stop a one-person lab clearing its own flag.
    if args.actor or tag:
        rec["review_waived_by"] = args.actor or tag
    write_json(run_dir(problem, rid) / "ingest.json", rec)
    commit(root, [rel(run_dir(problem, rid), root)],
           "%s review waived: %s" % (rid, args.reason[:60]))
    print("%s: review waived — %s" % (rid, args.reason))
    push_own_branch(root, tag)


# ------------------------------------------------- join, whoami, rebuild

def cmd_join(args):
    """Register this investigator and put them on their own branch. Everyone
    writing the record to one shared branch spends the day on pushes that are
    rejected, merged and conflicted over generated files — and two people
    reaching for the same next ID renumber each other's evidence by hand."""
    root = lab_root(args.problem)
    name = claims.git_user(root)
    tag = own_tag(root)
    branch = own_branch(tag)
    known = claims.registry_anywhere(root).get(tag)
    if known and known.get("name") != name:
        refuse("the tag %s is already taken by %r, and you are %r. A tag is "
               "made from git user.name and has to be unique here, or two "
               "people's IDs collide. Set a name that differs in its first %d "
               "letters or digits — `git config user.name \"...\"` — and join "
               "again." % (tag, known.get("name"), name, claims.TAG_MAX))
    if not has_ref(root, branch):
        r = git(root, "checkout", "-b", branch)
        if r.returncode != 0:
            refuse("git would not create branch %s:\n%s\nCommit or stash what "
                   "is in the tree, then join again."
                   % (branch, (r.stdout + r.stderr).strip()))
    elif current_branch(root) != branch:
        r = git(root, "checkout", branch)
        if r.returncode != 0:
            refuse("git would not check out %s:\n%s\nCommit or stash what is "
                   "in the tree, then join again."
                   % (branch, (r.stdout + r.stderr).strip()))
    install_hook(root)
    ensure_gitignore(root)
    # The registry is read again here: the branch just checked out carries
    # its own lab.json, and registering from the previous branch's copy
    # would drop whoever it does not know about.
    cfg = lab_config(root)
    reg = cfg.get("investigators") or {}
    if tag in reg:
        print("Already registered as %s (%s). You are on %s; nothing else "
              "changed." % (tag, name, branch))
        return
    reg[tag] = {"name": name, "host": host(), "joined": now()}
    cfg["investigators"] = reg
    (root / "lab.json").write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n")
    commit(root, ["lab.json", ".gitignore"], "join: %s (%s)" % (tag, name))
    push_own_branch(root, tag)
    print("Joined as %s (%s), on branch %s. Your runs and claims are now "
          "numbered in your own namespace (R-%s-001, C-%s-001); everything "
          "already on file keeps the ID it has. The others' work is read with "
          "`run.py catchup`, and agreed at a meeting with `run.py reconcile`."
          % (tag, name, branch, tag, tag))


def cmd_whoami(args):
    """Who this clone thinks you are, and what has not left it."""
    root = lab_root(args.problem)
    name = claims.git_user(root)
    tag = slug(name)
    reg = investigators(root)
    branch = current_branch(root)
    print("name: %s" % (name or "unset — `git config user.name \"Your Name\"`"))
    print("tag: %s%s" % (tag or "—",
                         "" if tag in reg else
                         " (not registered here — run `run.py join`)"))
    print("branch: %s%s" % (branch or "none",
                            "" if branch == own_branch(tag)
                            else " (your own branch is %s — `run.py join` "
                                 "checks it out)" % own_branch(tag)))
    n = unpushed(root, tag if tag in reg else None)
    print("unpushed: %s" % ("no remote" if n is None else n))


def rebuild_views(root, problems=None):
    """Regenerate every generated page from the record, and return the paths
    touched. A generated page merged by hand is a page that no longer says
    what the ledgers say; rebuilding is how a merge is resolved."""
    paths = []
    for p in problems or all_problems(root):
        claims.regenerate(p)
        paths += [rel(p / "claims", root), rel(p / "CLAIMS.md", root)]
        if (p / "notebook" / "entries").is_dir():
            regenerate_index(p)
            paths.append(rel(p / "notebook" / "INDEX.md", root))
    return [x for x in paths if x]


def cmd_rebuild(args):
    root = lab_root(args.problem)
    problems = [find_problem(args.problem)] if args.problem else all_problems(root)
    if not problems:
        refuse("there is no problem to rebuild under %s. Run this inside the "
               "lab, or pass --problem with a problem directory." % root)
    paths = rebuild_views(root, problems)
    commit(root, paths, "rebuild: views regenerated from the record")
    print("Rebuilt the views of %d problem(s) from the record: %s"
          % (len(problems), ", ".join(p.name for p in problems)))


# ---------------------------------------------------------- the meeting

GENERATED_NAMES = ("CLAIMS.md", "INDEX.md")
HAND_PAGES = ("STATUS.md", "OPEN_QUESTIONS.md", "README.md")
CLAIM_PAGE = re.compile(r"^C-(?:[a-z0-9][a-z0-9-]*-)?\d+\.md$")


def conflict_kind(path):
    """Which of three kinds a merge conflict is in. Generated pages are
    rebuilt from the record; a ledger is an append-only stream whose union is
    the answer; a hand-written page is a disagreement, and only the room
    settles that. Anything else is not this script's to resolve."""
    name = Path(path).name
    if name in GENERATED_NAMES or CLAIM_PAGE.match(name):
        return "generated"
    if name.startswith("ledger") and name.endswith(".jsonl"):
        return "ledger"
    if name in HAND_PAGES:
        return "page"
    if name == "lab.json":
        return "registry"
    return None


def merge_registry(root, path, tag, pages):
    """Both sides' lab.json, with the investigator lists added together. Two
    people joining on two branches each add one key to one map, and a
    conflict there would stop the first meeting the lab ever holds. Anything
    else in the file that differs is a change to the machine's settings, and
    goes to the room like any other hand-written page."""
    ours = json.loads(merge_stage(root, 2, path) or "{}")
    theirs = json.loads(merge_stage(root, 3, path) or "{}")
    people = dict(theirs.get("investigators") or {})
    people.update(ours.get("investigators") or {})
    merged = dict(ours)
    if people:
        merged["investigators"] = people
    (root / path).write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n")
    rest = [dict(d, investigators=None) for d in (ours, theirs)]
    if rest[0] != rest[1]:
        copy = "%s.%s" % (path, tag)
        (root / copy).write_text(merge_stage(root, 3, path))
        git(root, "add", "--", copy)
        pages.setdefault(path, []).append(tag)


def merge_stage(root, stage, path):
    return git(root, "show", ":%d:%s" % (stage, path)).stdout


def union_ledger(root, path):
    """Both sides' events, once each, in time order. An append-only file has
    no conflict in it: the lines are all true, and a hand-resolved ledger is
    a record somebody edited."""
    lines = [l for l in (merge_stage(root, 2, path).splitlines()
                         + merge_stage(root, 3, path).splitlines()) if l.strip()]
    lines = list(dict.fromkeys(lines))
    try:
        lines.sort(key=lambda l: json.loads(l)["ts"])
    except (json.JSONDecodeError, KeyError):
        pass
    (root / path).write_text("\n".join(lines) + "\n")


def merge_branch(root, ref, tag, pages):
    """Merge one investigator's branch into main. Namespaced files never
    collide; what is left is generated pages, which are rebuilt, and
    hand-written pages, which go on the agenda with both versions in the
    tree — never left half-merged for somebody to find later."""
    r = git(root, "merge", "--no-ff", "-m", "reconcile: merge %s" % ref, ref)
    if r.returncode == 0:
        return
    conflicts = git_out(root, "diff", "--name-only",
                        "--diff-filter=U").splitlines()
    unknown = [p for p in conflicts if conflict_kind(p) is None]
    if not conflicts or unknown:
        git(root, "merge", "--abort")
        refuse("merging %s stopped on %s, which reconcile does not resolve for "
               "you. Merge that branch by hand on main, commit, and run "
               "`run.py reconcile` again."
               % (ref, ", ".join(unknown) or "a conflict it cannot read:\n"
                  + (r.stdout + r.stderr).strip()))
    for p in conflicts:
        kind = conflict_kind(p)
        if kind == "ledger":
            union_ledger(root, p)
        elif kind == "registry":
            merge_registry(root, p, tag, pages)
        elif kind == "page":
            copy = "%s.%s" % (p, tag)
            (root / copy).write_text(merge_stage(root, 3, p))
            git(root, "checkout", "--ours", "--", p)
            git(root, "add", "--", copy)
            pages.setdefault(p, []).append(tag)
        else:
            git(root, "checkout", "--ours", "--", p)
        git(root, "add", "--", p)
    for p in rebuild_views(root):
        git(root, "add", "--", p)
    r = git(root, "commit", "--no-edit")
    if r.returncode != 0:
        refuse("git would not complete the merge of %s:\n%s"
               % (ref, (r.stdout + r.stderr).strip()))


def merge_refs(root):
    """Every branch the meeting merges: origin's copy of each investigator's
    branch and the local one, in tag order, so a branch pushed from another
    machine and one still only here both land."""
    out = []
    for tag in sorted(branch_tags(root)):
        for ref in ("origin/" + own_branch(tag), own_branch(tag)):
            if has_ref(root, ref):
                out.append((tag, ref))
    return out


def base_commit(root):
    """Where "since the last meeting" starts: the last meeting's commit, or
    the lab's first commit when there has not been one."""
    sha, when = last_meeting(root)
    if sha:
        return sha, when
    first = git_out(root, "rev-list", "--max-parents=0", "-n", "1", "main")
    return (first, commit_time(root, first)) if first else (None, None)


def pages_edited_on_branches(root, base, skip=()):
    """Hand-written pages more than one branch has rewritten since the last
    meeting. Two people rewriting the bottom line in two places is exactly
    what a meeting is for; nobody notices it from their own branch."""
    edits = {}
    if not base:
        return {}
    for tag, ref in merge_refs(root):
        for p in git_out(root, "diff", "--name-only", "%s..%s"
                         % (base, ref)).splitlines():
            if Path(p).name in HAND_PAGES and p not in skip:
                edits.setdefault(p, set()).add(tag)
    return {p: sorted(t) for p, t in edits.items() if len(t) > 1}


def stream_map(problem):
    """Every claim's events grouped by the stream that wrote them, so a
    disagreement between two streams can be named as one."""
    out = {}
    for path in claims.ledger_paths(problem):
        tag = claims.stream_tag(path)
        for line in path.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                out.setdefault(rec["id"], {}).setdefault(tag, []).append(rec)
    return out


def agenda_items(root, base, base_time, pages):
    """The meeting's agenda: everything two records disagree about, or one
    record has left open, each with the command that settles it."""
    items = []
    for p, tags in sorted(pages.items()):
        items.append(("%s was rewritten on more than one branch (%s)"
                      % (p, ", ".join(tags)),
                      "read %s beside %s, write the page the room agrees, "
                      "then delete the copies"
                      % (p, ", ".join("%s.%s" % (p, t) for t in tags))))
    for p, tags in sorted(pages_edited_on_branches(root, base,
                                                   skip=set(pages)).items()):
        items.append(("%s was edited on more than one branch since the last "
                      "meeting (%s), and merged without conflict"
                      % (p, ", ".join(tags)),
                      "read %s and confirm it says what the room believes" % p))

    for problem in all_problems(root):
        where = problem.name
        known, order = claims.load(problem)
        for i, a in enumerate(order):
            for b in order[i + 1:]:
                if id_tag(a) == id_tag(b):
                    continue
                if similar(known[a]["statement"], known[b]["statement"]):
                    items.append(("%s (%s) and %s (%s) state the same thing in "
                                  "two streams" % (a, id_tag(a) or "founding",
                                                   b, id_tag(b) or "founding"),
                                  "claims.py set %s superseded --by %s "
                                  "--actor \"meeting <date> (<tags>)\" "
                                  "--problem %s" % (a, b, where)))
        for cid, by_stream in sorted(stream_map(problem).items(), key=lambda x: id_key(x[0])):
            latest = {}
            for tag, evs in by_stream.items():
                last = max(evs, key=lambda r: r["ts"])
                if last["event"] != "new":
                    latest[tag] = last["to"]
            if len(set(latest.values())) > 1:
                items.append(("%s is %s" % (cid, " and ".join(
                    "%s in %s" % (st, t or "the founding stream")
                    for t, st in sorted(latest.items()))),
                    "the room decides, then `claims.py set %s <status> "
                    "--actor \"meeting <date> (<tags>)\" --problem %s`"
                    % (cid, where)))
        for cid in order:
            c = known[cid]
            if c["status"] != "verified":
                continue
            for r in c.get("rests_on") or []:
                rc = known.get(r)
                if rc and rc["status"] != "verified" and id_tag(r) != id_tag(cid):
                    items.append(("%s is verified and rests on %s, which "
                                  "another stream has left %s"
                                  % (cid, r, rc["status"]),
                                  "`claims.py set %s conditional` or verify %s "
                                  "again — the room decides which" % (cid, r)))
        stale, owed = {}, {}
        for rid, d in all_runs(problem):
            owner = run_owner(problem, rid) or "founding stream"
            if d["status"] == "open" and (not base_time or d["ts"] < base_time):
                stale.setdefault(owner, []).append(rid)
            ing = ingest_record(problem, rid) or {}
            if (ing.get("validation") == "review" and not ing.get("reviewed_by")
                    and not ing.get("review_waived")):
                owed.setdefault(owner, []).append(rid)
        for owner, rids in sorted(stale.items()):
            items.append(("%s has %d run(s) open since before the last meeting: "
                          "%s" % (owner, len(rids), ", ".join(rids)),
                          "%s ingests or voids each one" % owner))
        for owner, rids in sorted(owed.items()):
            items.append(("%s owes a review on %d run(s): %s"
                          % (owner, len(rids), ", ".join(rids)),
                          "dispatch a referee, or `run.py waive-review <run> "
                          "--reason ...`"))
        for line in duplicate_pairs(root, problem):
            items.append((line, "close the original, or void the duplicate"))
    return items


def write_agenda(root, date, items):
    d = meetings_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    lines = ["# Meeting agenda — %s" % date, "",
             "<!-- Generated by run.py reconcile. One line per thing two "
             "records disagree", "     about, or one record has left open. "
             "The room decides each in turn. -->", ""]
    for i, (what, how) in enumerate(items, 1):
        lines += ["%d. %s" % (i, what), "   - %s" % how]
    if not items:
        lines.append("Nothing to settle: every branch agrees.")
    path = agenda_path(root, date)
    path.write_text("\n".join(lines) + "\n")
    return path


def reconcile_open(root, tag, args):
    date = args.date or today()
    left = {p for p in dirty(root)
            if "__pycache__" not in p and not p.endswith(".pyc")}
    if left:
        refuse("the tree has uncommitted changes (%s%s). A meeting starts from "
               "a clean record, or the merge carries in work nobody has read. "
               "Commit them on %s, or put them aside, then run this again."
               % (", ".join(sorted(left)[:5]),
                  ", …" if len(left) > 5 else "", own_branch(tag)))
    n = unpushed(root, tag)
    if n:
        refuse("you have %d commit(s) on %s that origin does not, and the "
               "meeting merges what origin holds. Run `git push origin %s`, "
               "then run this again." % (n, own_branch(tag), own_branch(tag)))
    fetch(root)
    if has_ref(root, "main"):
        r = git(root, "checkout", "main")
    else:
        print("main did not exist; created from %s." % current_branch(root))
        r = git(root, "checkout", "-b", "main")
    if r.returncode != 0:
        refuse("git would not put this clone on main:\n%s"
               % (r.stdout + r.stderr).strip())
    base, base_time = base_commit(root)
    pages = {}
    refs = merge_refs(root)
    for other, ref in refs:
        merge_branch(root, ref, other, pages)
    commit(root, rebuild_views(root),
           "reconcile: views rebuilt from every stream")
    items = agenda_items(root, base, base_time, pages)
    path = write_agenda(root, date, items)
    commit(root, [rel(path, root)], "reconcile: agenda %s" % date)
    print("Merged %d branch(es) into main; last meeting: %s."
          % (len(refs), last_meeting(root)[1] or "none on record — everything "
             "since the lab started counts as new"))
    print("\nAgenda (%s), also written to %s:" % (date, rel(path, root)))
    for i, (what, how) in enumerate(items, 1):
        print("%d. %s\n   - %s" % (i, what, how))
    if not items:
        print("Nothing to settle: every branch agrees.")
    print("\nDecide each in turn, recording every decision as it is taken "
          "(`claims.py set ... --actor \"meeting %s (<tags>)\"`, edits to the "
          "pages above, `run.py note`). Then close the meeting with "
          "`run.py reconcile --close --present <tags>`." % date)


def leftover_copies(root):
    """Copies of a hand-written page left in the tree: a disagreement the
    room has not settled. Closing a meeting over one files minutes that
    disagree with the record."""
    out = []
    tags = known_tags(root)
    for p in Path(root).rglob("*"):
        if ".git" in p.parts or not p.is_file():
            continue
        name = p.name
        if "." in name and name.rsplit(".", 1)[-1] in tags:
            out.append(rel(p, root))
    return sorted(x for x in out if x)


def meeting_decisions(root, date):
    """What the room actually decided, taken from the record rather than
    from anyone's memory of the discussion."""
    out = []
    for problem in all_problems(root):
        for rec, _ in claims.stream_events(problem):
            if str(rec.get("actor", "")).startswith("meeting %s" % date):
                out.append(describe_event(rec))
    return out


def reconcile_close(root, tag, args):
    date = args.date or today()
    if current_branch(root) != "main":
        refuse("closing a meeting is done on main, and this clone is on %s. "
               "Run `git checkout main`, or `run.py reconcile` to prepare the "
               "meeting first." % (current_branch(root) or "no branch"))
    path = agenda_path(root, date)
    if not path.exists():
        refuse("there is no agenda at %s, so there is no meeting to close. "
               "Run `run.py reconcile` first." % rel(path, root))
    left = leftover_copies(root)
    if left:
        refuse("these copies of hand-written pages are still in the tree: %s. "
               "Each is a page two branches rewrote and the room has not "
               "settled. Write the agreed page, delete the copies, then close "
               "the meeting." % ", ".join(left))
    present = args.present or ",".join(sorted(known_tags(root)))
    tags = [t.strip() for t in present.split(",") if t.strip()]
    decisions = meeting_decisions(root, date)
    paths = rebuild_views(root)
    body = ["# Meeting — %s" % date, "",
            "**Present:** %s" % ", ".join(tags), "",
            "## Agenda", "", path.read_text().split("\n", 2)[-1].strip(), "",
            "## Decisions recorded", ""]
    body += ["- " + d for d in decisions] or [
        "- None recorded in the ledger under this meeting's actor."]
    note = meetings_dir(root) / ("%s.md" % date)
    note.write_text("\n".join(body) + "\n")
    paths += [rel(meetings_dir(root), root)]
    for p in all_problems(root):
        paths += [rel(p / n, root) for n in HAND_PAGES]
    # The copies the room read and deleted go into the same commit: a page
    # settled in the meeting and a copy left behind in the next branch is
    # the disagreement coming back a week later.
    paths += [p for p in dirty(root)
              if Path(p).name.rsplit(".", 1)[-1] in known_tags(root)]
    commit(root, paths, "%s%s (%s)" % (MEETING_PREFIX, date, ",".join(tags)))
    if has_remote(root):
        r = git(root, "push", "origin", "main")
        if r.returncode != 0:
            print("main is not pushed (%s); push it before anyone starts work."
                  % (r.stderr.strip().splitlines() or ["no reason given"])[-1][:100])
    behind = []
    for other in sorted(known_tags(root)):
        for ref in (own_branch(other), "origin/" + own_branch(other)):
            if has_ref(root, ref) and git(root, "merge-base", "--is-ancestor",
                                          ref, "main").returncode != 0:
                behind.append(ref)
    if behind:
        refuse("%s carr%s commits main does not, made after the meeting "
               "began, so fast-forwarding would drop them. Merge them into "
               "main first (`run.py reconcile` again), then close."
               % (", ".join(behind), "ies" if len(behind) == 1 else "y"))
    for other in sorted(known_tags(root)):
        branch = own_branch(other)
        if has_ref(root, branch):
            git(root, "branch", "-f", branch, "main")
        if has_remote(root) and has_ref(root, "origin/" + branch):
            r = git(root, "push", "origin", "main:" + branch)
            if r.returncode != 0:
                print("%s is not fast-forwarded on origin (%s); that "
                      "investigator does it themselves with `git pull "
                      "--ff-only`."
                      % (branch,
                         (r.stderr.strip().splitlines() or ["?"])[-1][:80]))
    git(root, "checkout", own_branch(tag))
    print("Meeting %s closed and filed as %s. Present: %s. %d decision(s) on "
          "record. Every branch now starts from main; you are back on %s."
          % (date, rel(note, root), ", ".join(tags), len(decisions),
             own_branch(tag)))


def cmd_reconcile(args):
    root = lab_root(args.problem)
    if not joined(root):
        refuse("no investigator has joined this lab, so there is nothing to "
               "reconcile. Run `run.py join` — one investigator, one branch — "
               "and the meeting has something to merge.")
    tag = own_tag(root)
    if tag not in investigators(root):
        refuse("you are not registered in this lab, and the meeting is run "
               "from a registered investigator's clone. Run `run.py join` "
               "first.")
    if args.close:
        reconcile_close(root, tag, args)
    else:
        reconcile_open(root, tag, args)


# ---------------------------------------------------------------- cli

def main(argv=None):
    p = argparse.ArgumentParser(prog="run.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="dispatch a worker")
    n.add_argument("--brief", required=True)
    n.add_argument("--model", help="overrides the model in lab.json")
    n.add_argument("--role", default="technician")
    n.add_argument("--actor", help="who the record credits (default: the model)")
    n.add_argument("--checks", metavar="RUN",
                   help="the ingested run this dispatch referees; ingest fills "
                        "`reviewed` from it when the packet leaves it out")
    n.add_argument("--duplicates", metavar="RUN",
                   help="the run this one deliberately repeats, usually "
                        "another investigator's; catchup names the pair while "
                        "the original is still open")
    n.add_argument("--timeout", type=int, default=600,
                   help="seconds the replay gets at ingest")
    n.add_argument("--allow", action="append",
                   help="a path this worker may write; repeatable. The run "
                        "directory is always allowed")
    n.add_argument("--worker-timeout", type=int, metavar="SECONDS",
                   help="wall-clock budget for the worker (default: the "
                        "role's worker_timeout); a breach is recorded and "
                        "reported, never enforced")
    n.add_argument("--memory-gb", type=float, metavar="GB",
                   help="resident-memory budget for the worker's process tree "
                        "(default: the role's memory_gb); a breach is recorded "
                        "and reported, never enforced")
    n.add_argument("--detach", action="store_true",
                   help="launch, leave a watcher behind, and return at once")
    n.add_argument("--accept-same-model", action="store_true",
                   help="with --checks: dispatch the referee on the same model "
                        "as the run it checks, knowingly")
    n.add_argument("--force", action="store_true",
                   help="dispatch even though an open run carries this same "
                        "brief")
    n.add_argument("--no-launch", action="store_true",
                   help="prepare the run without starting the worker")
    n.set_defaults(func=cmd_new)

    i = sub.add_parser("ingest", help="file a returned packet")
    i.add_argument("run")
    i.add_argument("--reason",
                   help="with --record-broken: why the run failed, in your "
                        "words; required when no refusal or worker exit is on "
                        "record, and filed first when there is")
    i.add_argument("--reviewed", action="append", metavar="R-NNN",
                   help="the run(s) this packet refereed, overriding the "
                        "packet's own `reviewed` list — so a good packet is "
                        "never discarded over one wrong ID")
    i.add_argument("--record-broken", action="store_true",
                   help="file the failure as it stands: UNINGESTABLE when a "
                        "packet exists, HARNESS-FAILURE when none does; the "
                        "recorded reason goes in the entry, no claims")
    i.add_argument("--transcript", metavar="PATH",
                   help="the worker's session file, when the role's rule "
                        "cannot find it — for a worker the Director drove "
                        "itself, say")
    i.add_argument("--worker-done", action="store_true",
                   help="ingest even though execution.json says the worker "
                        "process is still alive")
    i.set_defaults(func=cmd_ingest)

    v = sub.add_parser("void", help="close a run that produced nothing")
    v.add_argument("run")
    v.add_argument("--reason", required=True)
    v.set_defaults(func=cmd_void)

    l = sub.add_parser("lint", help="read-only packet contract check")
    l.add_argument("run")
    l.set_defaults(func=cmd_lint)

    w = sub.add_parser("waive-review", help="record that an owed review "
                                            "will not happen")
    w.add_argument("run")
    w.add_argument("--reason", required=True)
    w.add_argument("--actor", help="who is waiving it (default: your "
                                   "investigator tag, once anyone has joined "
                                   "the lab)")
    w.set_defaults(func=cmd_waive_review)

    t = sub.add_parser("note", help="file a Director-written notebook entry")
    t.add_argument("--headline", required=True)
    t.add_argument("--body")
    t.add_argument("--body-file")
    t.add_argument("--actor", help="who the entry is credited to (default: "
                                   "your investigator tag, once anyone has "
                                   "joined the lab)")
    t.set_defaults(func=cmd_note)

    c = sub.add_parser("catchup", help="what changed since a commit or a date")
    c.add_argument("since", nargs="?",
                   help="a commit, or YYYY-MM-DD (default: the last meeting, "
                        "else the last seven days)")
    c.set_defaults(func=cmd_catchup)

    tr = sub.add_parser("transcript", help="attach a worker's session file to "
                                          "a run already on record")
    tr.add_argument("run")
    tr.add_argument("--path", metavar="FILE",
                    help="the session file, when the role's rule cannot find it")
    tr.add_argument("--replace", action="store_true",
                    help="replace a transcript already on record")
    tr.set_defaults(func=cmd_transcript)

    j = sub.add_parser("join", help="register this investigator and check out "
                                    "their own branch")
    j.set_defaults(func=cmd_join)

    m = sub.add_parser("whoami", help="tag, branch, and what is unpushed")
    m.set_defaults(func=cmd_whoami)

    b = sub.add_parser("rebuild", help="regenerate every generated view from "
                                       "the record; changes nothing else")
    b.set_defaults(func=cmd_rebuild)

    rc = sub.add_parser("reconcile", help="the meeting: merge every branch "
                                          "into main and settle the agenda")
    rc.add_argument("--close", action="store_true",
                    help="record the meeting: file the note, commit, and "
                         "fast-forward every branch to main")
    rc.add_argument("--present", help="with --close: the tags in the room, "
                                      "comma separated")
    rc.add_argument("--date", help="the meeting's date (default: today, UTC)")
    rc.set_defaults(func=cmd_reconcile)

    # Every subcommand takes --problem, including the lab-wide ones, where
    # it says which clone to work in rather than which problem: a flag that
    # is right on six commands and unknown on four is a flag nobody trusts.
    for q in (n, i, t, c, v, l, w, b, tr, j, m, rc):
        q.add_argument("--problem", help="the problem directory (default: found "
                                         "by walking up from here); for "
                                         "lab-wide commands, any directory in "
                                         "the lab")
    g = sub.add_parser("guard-commit", help="pre-commit hook: refuse a hand "
                                            "commit of an open run's files, or "
                                            "of another investigator's run")
    g.set_defaults(func=cmd_guard_commit)
    args = p.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
