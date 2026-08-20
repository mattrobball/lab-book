#!/usr/bin/env python3
"""Runs: dispatch a worker, ingest what it returns, keep the notebook.

new      allocate R-NNN, record dispatch.json, assemble PROMPT.md and the
         run-local worker charter, launch the worker in the run directory.
ingest   gate the returned packet, replay its evidence, compute the honesty
         tier, allocate proposed claims, file the notebook entry, commit.
note     file a Director-written entry: headline, body, actor. No packet.
catchup  what changed since a commit or a date.
check    advisory lint: open runs, reviews owed, STATUS.md staleness.

Claim IDs, status and the ledger belong to claims.py; this file imports it and
never touches claims/ by hand.

Three conventions this file settles:

* The replay command is the first fenced or indented code block inside the
  packet's `## Validation` section. It runs with the run directory as its
  working directory, under the timeout recorded at dispatch.
* The honesty tier is computed here and never copied from the worker. Replay
  declared, exit 0 inside the timeout, and every marker present as an exact
  substring is `machine-verified`; anything else at this ingest is `asserted`,
  with a warning saying which of the three failed. `hand-checked` is written
  later: when a referee run whose RETURN.json lists this run in `reviewed` is
  ingested with verdict PASS, by a different actor.
* A packet that fails a gate is refused, not filed. Filing a bad packet is a
  separate deliberate act: `ingest R-NNN --record-broken`, which commits the
  packet as it stands under verdict UNINGESTABLE and allocates no claims.
"""
import argparse
import contextlib
import hashlib
import io
import json
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import claims                                    # noqa: E402  (sibling script)
from claims import refuse, now, git_root         # noqa: E402

RUN_ID = re.compile(r"^R-\d+$")
CLAIM_ID = re.compile(r"\bC-\d+\b")
VERDICT_LINE = re.compile(r"^#\s*VERDICT:\s*(PASS|FAIL|UNDECIDED)\s*$")
FENCE = re.compile(r"```[a-zA-Z0-9]*\n(.+?)\n```", re.S)
INDENTED = re.compile(r"^(?: {4}|\t)(\S.*)$", re.M)
INDEX_META = re.compile(r"<!-- index: (.*?) -->")
SECTIONS = ["What was done", "Not claimed", "Leads", "Validation"]
REQUIRED = ["headline", "exits", "validation", "machine_markers",
            "honesty_tier", "claims_used", "claims_proposed"]
STOP = {"the", "a", "an", "of", "is", "in", "on", "for", "to", "and", "at",
        "has", "have", "every", "all", "with", "that", "this", "it", "are"}

CHARTER = """## Who you are

You are the Technician on run {rid}. You were dispatched to do one task and
return a packet saying what happened. You have no history here and no other
context: this prompt is everything you were given. Do the task in front of you
and nothing else.

## Your fence

You may create or modify files only under these paths:

{allowed}

Anything written outside them makes this run unusable, and the run is refused
at ingest rather than filed.

- Run no `git` commands of any kind. The lab records itself.
- Never invent a claim ID. Copy into `claims_used` exactly the IDs the brief
  pastes, and nothing else. New claims go in `claims_proposed` as plain
  sentences; the lab allocates their IDs when this run is ingested.
- Do not name yourself anywhere in the packet. The lab stamps who ran this.

## What you must return

Both of these files, under `{packet}`:

`RESULT.md`

- First line exactly `# VERDICT: PASS`, `# VERDICT: FAIL` or
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
  referee other than you must check, step by step. The replay command is run
  with this directory as its working directory, under a {timeout}s timeout.

`RETURN.json` — plain JSON, no comments:

- `headline` — one sentence, the same result the verdict line states.
- `exits` — the states you actually reached, as short strings.
- `validation` — `replay` or `review`, matching the block above.
- `machine_markers` — the exact strings a passing replay prints; ingest looks
  for each one character for character, never by pattern.
- `honesty_tier` — your own reading: `machine-verified`, `hand-checked` or
  `asserted`. Ingest computes the tier that goes on record and only compares
  yours against it.
- `claims_used` — the claim IDs copied from the brief.
- `claims_proposed` — new claims as plain statements, never IDs.

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


def lab_config(root):
    p = root / "lab.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as e:
        refuse("%s is not valid JSON (%s). Fix that file — it holds the models "
               "and launch commands for this machine." % (p, e))


def fingerprint(text):
    return hashlib.sha256(" ".join(text.split()).lower().encode()).hexdigest()


def split_sections(text):
    parts = claims.HEADING.split(text)
    return {parts[i].strip().lower(): parts[i + 1].strip()
            for i in range(1, len(parts) - 1, 2)}


# ---------------------------------------------------------------- git

def git(root, *args):
    return subprocess.run(["git"] + list(args), cwd=str(root),
                          capture_output=True, text=True)


def head(root):
    r = git(root, "rev-parse", "HEAD")
    if r.returncode != 0:
        refuse("this repository has no commits yet, so there is no position to "
               "record for the dispatch. Commit what is here first, then "
               "dispatch.")
    return r.stdout.strip()


def dirty(root):
    out = set()
    for line in git(root, "status", "--porcelain").stdout.splitlines():
        p = line[3:]
        if " -> " in p:
            p = p.split(" -> ")[-1]
        out.add(p.strip().strip('"'))
    return out


def commit(root, paths, message):
    paths = [p for p in paths if p and (root / p).exists()]
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


def allocate_run(problem):
    """mkdir is atomic: two dispatchers racing here cannot both take the ID."""
    d = problem / "runs"
    d.mkdir(parents=True, exist_ok=True)
    taken = [int(p.name[2:]) for p in d.iterdir() if RUN_ID.match(p.name)]
    n = max(taken) if taken else 0
    while True:
        n += 1
        rid = "R-%03d" % n
        try:
            (d / rid).mkdir()
        except FileExistsError:
            continue
        return rid


def all_runs(problem):
    d = problem / "runs"
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.iterdir()):
        if RUN_ID.match(p.name) and (p / "dispatch.json").exists():
            out.append((p.name, json.loads((p / "dispatch.json").read_text())))
    return out


def ingest_record(problem, rid):
    p = run_dir(problem, rid) / "ingest.json"
    return json.loads(p.read_text()) if p.exists() else None


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------- notebook

def slugify(text, words=6):
    return "-".join(re.findall(r"[a-z0-9]+", text.lower())[:words]) or "entry"


def file_entry(problem, headline, meta, body):
    d = problem / "notebook" / "entries"
    d.mkdir(parents=True, exist_ok=True)
    day = time.strftime("%Y%m%d", time.gmtime())
    n = 1 + len([p for p in d.iterdir() if p.name.startswith("N-%s-" % day)])
    path = d / ("N-%s-%02d-%s.md" % (day, n, slugify(headline)))
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


# ---------------------------------------------------------------- new

def cmd_new(args):
    problem = find_problem(args.problem)
    root = git_root(problem)
    brief = Path(args.brief)
    if not brief.is_file():
        refuse("there is no brief at %s. Write one from templates/BRIEF.md and "
               "pass its path to --brief." % args.brief)
    text = brief.read_text()
    role = lab_config(root).get("roles", {}).get(args.role, {})
    model = args.model or role.get("model")
    if not model:
        refuse("this dispatch names no model. Pass --model, or add "
               "roles.%s.model to %s/lab.json. An unset model quietly inherits "
               "this session's model and spends an expensive one on a cheap "
               "job." % (args.role, root))

    fp = fingerprint(text)
    for rid, d in all_runs(problem):
        if d.get("brief_fingerprint") == fp and d.get("status") == "open":
            print("Warning: %s is still open and carries the same brief. "
                  "Ingest it first, or say in this brief how the question "
                  "differs — dispatching the same question twice is usually a "
                  "lost thread." % rid)

    before, position = dirty(root), head(root)
    rid = allocate_run(problem)
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
    charter = CHARTER.format(rid=rid, timeout=args.timeout,
                             packet="%s/packet/" % rundir_rel,
                             allowed="\n".join("- `%s`" % a for a in allowed))
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
        "claims_pasted": sorted(set(CLAIM_ID.findall(text))),
        "timeout": args.timeout, "git_head": position, "allowed": allowed,
        # Already dirty before this dispatch, so the fence check at ingest
        # cannot blame the worker for it. The brief joins the list because
        # this dispatch commits it itself.
        "ignore": sorted(before | {rel(brief, root)} - {None}),
        "command": (role.get("command") or "").replace(
            "{prompt}", "%s/PROMPT.md" % rundir_rel) or None,
    }
    write_json(rundir / "dispatch.json", dispatch)
    commit(root, [rundir_rel, rel(brief, root)],
           "%s dispatched to %s" % (rid, model))
    print("%s — model %s, timeout %ss, may write: %s"
          % (rid, model, args.timeout, ", ".join(allowed)))

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
    log = rundir / "worker.log"
    print("Launching: %s\nWorker output (both streams) goes to %s/worker.log — "
          "`tail -f` it to watch." % (line, rundir_rel))
    sys.stdout.flush()
    with open(log, "wb") as fh:           # a worker that dies at its API says
        r = subprocess.run(shlex.split(line), cwd=str(rundir),   # so only here
                           stdout=fh, stderr=subprocess.STDOUT)
    size = log.stat().st_size
    print("Worker exited %d, %d byte(s) in %s/worker.log.%s Ingest with "
          "`run.py ingest %s`."
          % (r.returncode, size, rundir_rel,
             "" if size else " It printed nothing at all, which usually means "
             "it never really started — read the log before the packet.", rid))


# ---------------------------------------------------------------- ingest

def load_dispatch(problem, rid):
    p = run_dir(problem, rid) / "dispatch.json"
    if not p.exists():
        refuse("there is no run %s under %s/runs. Run `run.py check` to see "
               "which runs are on file." % (rid, problem.name))
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
    m = FENCE.search(validation_text)
    if not m:
        m = INDENTED.search(validation_text)
    return m.group(1).strip().splitlines()[0].strip() if m else None


def do_replay(rundir, secs, ret, rid, timeout):
    """Returns (tier, warnings, replay record). Nonzero exit fails whatever
    was printed; markers must appear character for character."""
    if ret["validation"] == "review":
        return "asserted", ["validation is a review and no referee run has "
                            "checked this yet, so nothing here is machine-"
                            "checked"], None
    cmd = replay_command(secs["validation"])
    if not cmd:
        refuse("%s declares validation `replay` but its `## Validation` section "
               "holds no command — I look for the first indented or fenced code "
               "block there. Recovery is a fresh dispatch, or `run.py ingest %s "
               "--record-broken`." % (rid, rid))
    record = {"command": cmd, "timeout": timeout}
    try:
        r = subprocess.run(cmd, shell=True, cwd=str(rundir), capture_output=True,
                           text=True, timeout=timeout)
        out, code = r.stdout + r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        record["exit"] = None
        return "asserted", ["the replay did not finish inside the %ss timeout "
                            "this dispatch set" % timeout], record
    record["exit"] = code
    missing = [m for m in ret["machine_markers"] if m not in out]
    if code != 0:
        return "asserted", ["the replay exited %d; a nonzero exit fails "
                            "whatever was printed" % code], record
    if missing:
        return "asserted", ["the replay never printed %s, and markers are "
                            "matched character for character, never by pattern"
                            % ", ".join(repr(m) for m in missing)], record
    return "machine-verified", [], record


def allocate_claim(problem, statement, actor):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        claims.main(["new", "--statement", statement, "--actor", actor,
                     "--problem", str(problem)])
    return buf.getvalue().strip().splitlines()[-1]


def near_duplicates(problem, statement):
    """Crude on purpose: normalized word overlap against every statement on
    file. It warns, it never blocks — only a reader can tell two claims apart."""
    def toks(s):
        return set(re.findall(r"[a-z0-9]+", s.lower())) - STOP
    a = toks(statement)
    hits = []
    if not a:
        return hits
    known, order = claims.load(problem)
    for cid in order:
        b = toks(known[cid]["statement"])
        if b and len(a & b) / float(len(a | b)) >= 0.6:
            hits.append(cid)
    return hits


def apply_reviews(problem, rid, ret, verdict, actor):
    """A referee run names the run it checked in RETURN.json `reviewed`.

    A review only ever lifts `asserted` to `hand-checked`. It never rewrites
    `machine-verified`, which a replay this lab ran had already earned — a
    referee reading the work is not evidence against a check that passed. The
    referee is recorded on the reviewed run either way, in `reviewed_by`."""
    notes, touched = [], []
    for target in ret.get("reviewed") or []:
        prev = ingest_record(problem, target) if RUN_ID.match(str(target)) else None
        if prev is None:
            refuse("RETURN.json says this run reviewed %s, but there is no "
                   "ingested run %s here. Name a run this lab ingested, or drop "
                   "the field." % (target, target))
        if verdict != "PASS":
            notes.append("%s stays %s: a review counts only when the referee "
                         "returns PASS." % (target, prev["honesty_tier"]))
            continue
        if prev["actor"].strip().casefold() == actor.strip().casefold():
            refuse("%s was run by %s and so was this one. A review by the same "
                   "actor validates nothing — dispatch a referee with a "
                   "different actor." % (target, prev["actor"]))
        prev["reviewed_by"] = sorted(set(prev.get("reviewed_by") or []) | {rid})
        if prev["honesty_tier"] == "asserted":
            prev["honesty_tier"] = "hand-checked"
            notes.append("%s is now hand-checked, reviewed by %s." % (target, rid))
            stamp_tier(problem, target, "hand-checked")
        else:
            notes.append("%s stays %s and records the review by %s: a review "
                         "never overwrites a tier a replay earned."
                         % (target, prev["honesty_tier"], rid))
        write_json(run_dir(problem, target) / "ingest.json", prev)
        touched.append(target)
    return notes, touched


def stamp_tier(problem, rid, tier):
    """dispatch.json carries a copy of the tier; keep it from going stale."""
    path = run_dir(problem, rid) / "dispatch.json"
    d = json.loads(path.read_text())
    d["honesty_tier"] = tier
    write_json(path, d)


def cmd_ingest(args):
    problem = find_problem(args.problem)
    root = git_root(problem)
    rid, rundir = args.run, run_dir(problem, args.run)
    d = load_dispatch(problem, rid)
    actor = d["actor"]

    if args.record_broken:
        d.update(status="uningestable", verdict="UNINGESTABLE", ingested_at=now())
        write_json(rundir / "dispatch.json", d)
        write_json(rundir / "ingest.json",
                   {"run": rid, "ts": now(), "actor": actor,
                    "verdict": "UNINGESTABLE", "honesty_tier": "asserted",
                    "validation": None, "headline": "packet filed unread",
                    "claims": [], "warnings": ["filed with --record-broken: "
                                               "the packet did not pass the "
                                               "gates and nothing in it counts"]})
        entry = file_entry(problem, "%s returned a packet that could not be "
                                    "ingested" % rid,
                           "%s | %s | UNINGESTABLE | packet filed as it stands"
                           % (time.strftime("%Y-%m-%d", time.gmtime()), rid),
                           "**Run:** %s · **Actor:** %s · **Verdict:** "
                           "UNINGESTABLE\n\nThe packet is committed as it "
                           "stands. No claims were allocated and nothing in it "
                           "is on record. Packets are never hand-edited; "
                           "recovery is a fresh dispatch." % (rid, actor))
        commit(root, [rel(rundir, root), rel(problem / "notebook", root)],
               "%s UNINGESTABLE (packet filed as it stands)" % rid)
        print("%s filed as UNINGESTABLE. No claims allocated. Entry: %s"
              % (rid, rel(entry, root)))
        return

    verdict, secs, ret = read_packet(problem, rid, d)

    changed = set(git(root, "diff", "--name-only", d["git_head"], "HEAD").stdout.split())
    changed = (changed | dirty(root)) - set(d.get("ignore") or [])
    bad = outside(changed, d["allowed"])
    if bad:
        refuse("%s wrote outside its fence: %s. It was allowed %s and nothing "
               "else. The run is not filed. Recovery is a fresh dispatch with "
               "the fence stated in the brief, or `run.py ingest %s "
               "--record-broken` to file the packet as it stands."
               % (rid, ", ".join(bad), ", ".join(d["allowed"]), rid))

    tier, warnings, replay = do_replay(rundir, secs, ret, rid, d["timeout"])
    if ret.get("honesty_tier") and ret["honesty_tier"] != tier:
        warnings.append("the worker reported %s; this ingest computes %s"
                        % (ret["honesty_tier"], tier))
    notes, touched = apply_reviews(problem, rid, ret, verdict, actor)

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
            "**Honesty:** %s%s" % (tier, "" if tier == "machine-verified"
                                   else " — " + "; ".join(warnings)),
            "**Validation:** %s%s" % (ret["validation"],
                                      " — `%s`" % replay["command"] if replay else ""),
            "", "## Headline", "", ret["headline"], "", "## Markers checked", ""]
    body += ["- `%s`" % m for m in ret["machine_markers"]] or ["- None declared."]
    body += ["", "## Claims allocated", ""]
    body += ["- %s — %s" % (c, s) for c, s in allocated] or ["- None."]
    if notes:
        body += ["", "## Reviews", ""] + ["- " + n for n in notes]
    body += ["", "## Leads", "", secs["leads"], "", "## Packet", "",
             "`%s/packet/RESULT.md` · `%s/packet/RETURN.json`"
             % (rel(rundir, root), rel(rundir, root))]
    entry = file_entry(problem, ret["headline"],
                       "%s | %s | %s | %s" % (time.strftime("%Y-%m-%d", time.gmtime()),
                                              rid, verdict, ret["headline"]),
                       "\n".join(body))

    record = {"run": rid, "ts": now(), "actor": actor, "verdict": verdict,
              "headline": ret["headline"], "honesty_tier": tier,
              "validation": ret["validation"], "replay": replay,
              "claims": [c for c, _ in allocated], "warnings": warnings,
              "entry": rel(entry, root), "reviewed": ret.get("reviewed") or []}
    write_json(rundir / "ingest.json", record)
    d.update(status="ingested", verdict=verdict, ingested_at=record["ts"],
             honesty_tier=tier)
    write_json(rundir / "dispatch.json", d)
    paths = [rel(rundir, root), rel(problem / "notebook", root)]
    paths += [rel(run_dir(problem, t), root) for t in touched]
    commit(root, paths, "%s ingested: %s — %s" % (rid, verdict, ret["headline"]))

    print("%s %s (%s)" % (rid, verdict, tier))
    for w in warnings + notes:
        print("- " + w)
    for cid, s in allocated:
        print("- %s proposed: %s" % (cid, claims.one_line(s)))
    print("Entry: %s" % rel(entry, root))


# ---------------------------------------------------------------- note

def cmd_note(args):
    problem = find_problem(args.problem)
    root = git_root(problem)
    body = Path(args.body_file).read_text() if args.body_file else (args.body or "")
    if not body.strip():
        refuse("a note needs a body: pass --body with the text or --body-file "
               "with a path. A headline with nothing under it tells a later "
               "reader nothing.")
    entry = file_entry(problem, args.headline,
                       "%s | note | — | %s" % (time.strftime("%Y-%m-%d", time.gmtime()),
                                               args.headline),
                       "**Actor:** %s · **Kind:** Director note (no packet, no "
                       "claims)\n\n%s" % (args.actor, body.strip()))
    commit(root, [rel(problem / "notebook", root)], "note: %s" % args.headline)
    print("Entry: %s" % rel(entry, root))


# ---------------------------------------------------------------- catchup

def cmd_catchup(args):
    problem = find_problem(args.problem)
    root = git_root(problem)
    since = args.since
    if re.match(r"^\d{4}-\d{2}-\d{2}$", since):
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
            lines.append("%s %s (%s) — %s" % (rid, ing["verdict"],
                                              ing["honesty_tier"], ing["headline"]))
    print("\nRuns:")
    print("\n".join("  " + l for l in lines) if lines else "  nothing")

    moves = []
    path = problem / "claims" / "ledger.jsonl"
    if path.exists():
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec["ts"] < cutoff:
                continue
            if rec["event"] == "new":
                moves.append("%s stated as %s by %s"
                             % (rec["id"], rec["status"], rec["actor"]))
            else:
                moves.append("%s %s -> %s by %s%s"
                             % (rec["id"], rec["from"], rec["to"], rec["actor"],
                                " (%s)" % rec["evidence"] if rec.get("evidence") else ""))
    print("\nClaims:")
    print("\n".join("  " + m for m in moves) if moves else "  nothing")

    open_runs = ["%s (%s, dispatched %s)" % (rid, d["model"], d["ts"])
                 for rid, d in all_runs(problem) if d["status"] == "open"]
    print("\nStill open:")
    print("\n".join("  " + o for o in open_runs) if open_runs else "  nothing")

    stamp = git(root, "log", "-1", "--format=%ct", "--",
                str(problem / "STATUS.md")).stdout.strip()
    if not stamp:
        print("\nSTATUS.md has never been committed, so everything above is "
              "missing from it.")
    else:
        cut = datetime.fromtimestamp(int(stamp), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        n = len([1 for rid, _ in all_runs(problem)
                 if (ingest_record(problem, rid) or {}).get("ts", "") > cut])
        print("\nSTATUS.md last changed %s; %d run(s) ingested since." % (cut, n))


# ---------------------------------------------------------------- check

def cmd_check(args):
    problem = find_problem(args.problem)
    known, _ = claims.load(problem)
    flags = []
    for rid, d in all_runs(problem):
        ing = ingest_record(problem, rid)
        if d["status"] == "open":
            flags.append("%s is still open — dispatched %s to %s and never "
                         "ingested." % (rid, d["ts"], d["model"]))
        if ing and ing.get("validation") == "review" and \
                ing["honesty_tier"] != "hand-checked":
            flags.append("%s declared a review and no referee has done it, so "
                         "it stays asserted. Dispatch a referee whose "
                         "RETURN.json lists %s in `reviewed`." % (rid, rid))
        for c in d.get("claims_pasted") or []:
            if c not in known:
                flags.append("%s pasted %s into its brief, and that is not a "
                             "claim in this ledger." % (rid, c))
    if flags:
        print("%d thing(s) to look at:" % len(flags))
        for f in flags:
            print("- " + f)
    else:
        print("Nothing to flag in %d run(s)." % len(all_runs(problem)))


# ---------------------------------------------------------------- cli

def main(argv=None):
    p = argparse.ArgumentParser(prog="run.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="dispatch a worker")
    n.add_argument("--brief", required=True)
    n.add_argument("--model", help="overrides the model in lab.json")
    n.add_argument("--role", default="technician")
    n.add_argument("--actor", help="who the record credits (default: the model)")
    n.add_argument("--timeout", type=int, default=600,
                   help="seconds the replay gets at ingest")
    n.add_argument("--allow", action="append",
                   help="a path this worker may write; repeatable. The run "
                        "directory is always allowed")
    n.add_argument("--no-launch", action="store_true",
                   help="prepare the run without starting the worker")
    n.set_defaults(func=cmd_new)

    i = sub.add_parser("ingest", help="file a returned packet")
    i.add_argument("run")
    i.add_argument("--record-broken", action="store_true",
                   help="file an ungateable packet as it stands, verdict "
                        "UNINGESTABLE, allocating no claims")
    i.set_defaults(func=cmd_ingest)

    t = sub.add_parser("note", help="file a Director-written notebook entry")
    t.add_argument("--headline", required=True)
    t.add_argument("--body")
    t.add_argument("--body-file")
    t.add_argument("--actor", required=True)
    t.set_defaults(func=cmd_note)

    c = sub.add_parser("catchup", help="what changed since a commit or a date")
    c.add_argument("since", help="a commit, or YYYY-MM-DD")
    c.set_defaults(func=cmd_catchup)

    k = sub.add_parser("check", help="advisory lint; never fails")
    k.set_defaults(func=cmd_check)

    for q in (n, i, t, c, k):
        q.add_argument("--problem", help="the problem directory (default: found "
                                         "by walking up from here)")
    args = p.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
