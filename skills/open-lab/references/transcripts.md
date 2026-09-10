# Transcripts: worked examples

A worker's `worker.log` is what it printed. Its reasoning and tool calls
live in its command's own session store, in a shape that store decides and
may change. So the kit records no rules — it records examples, and the
Director derives each lab's rules from a file a real run of that lab wrote:

    run.py transcript R-NNN --discover      # files written during the run
    run.py transcript R-NNN --accept 3      # record candidate 3's rule

`--accept` writes `roles.<role>.transcript` into `lab.local.json` with the
glob, the match rule, and the run, path and first line that justified it.
From then on ingest finds the file itself. Transcripts are on unless
`lab.json` says `"transcripts": {"enabled": false}` or a role says
`"transcript": false`; off means not looked for and not counted missing.

Below, one real example per tool family seen so far, as they stood on one
machine in September 2026. Compare, do not copy: if the file `--discover`
shows you looks like one of these, the derived rule will match it; if not,
the store has moved and the example is the thing to update.

## codex

Path, one JSONL per session under a date tree, the working directory in the
first line one level down inside `payload`:

    ~/.codex/sessions/2026/09/10/rollout-2026-09-10T13-33-33-01a08c61-….jsonl
    {"timestamp": "…", "type": "session_meta", "payload": {"cwd": "/…/runs/R-212", …}}

Derived rule: `~/.codex/sessions/*/*/*/*.jsonl`, match `first-line-cwd`.

Usage: lines of `"type": "token_usage_record"` carry
`payload.usage.{input_tokens, output_tokens, total_tokens}` per turn; ingest
sums them.

## claude

Path, a folder named after the working directory with every `/` turned into
`-`, one JSONL per session inside it:

    ~/.claude/projects/-Users-worker-lab-problems-p-runs-R-211/fce75688-….jsonl
    {"type": "summary", …}                       first line names no cwd

Derived rule: `~/.claude/projects/{cwd_dashed}/*.jsonl`, match `path`.

Usage: assistant lines carry `message.usage.{input_tokens,
cache_read_input_tokens, cache_creation_input_tokens, output_tokens}`;
ingest sums input plus both cache figures as input.

## grok

Path, a folder named after the URL-encoded working directory, a session-id
folder inside it, fixed file names:

    ~/.grok/sessions/%2FUsers%2Fworker%2Flab%2F…%2Fruns%2FR-212/01a07e95-…/chat_history.jsonl
    {"type": "system", …}                        first line names no cwd

Derived rule: `~/.grok/sessions/{cwd_urlencoded}/*/chat_history.jsonl`,
match `path`. `events.jsonl` beside it is the tool-call log; `summary.json`
names the model and the head commit.

Usage: none of the session files carry token counts. Recorded as absent.

## opencode (muse, inkling, ox)

Sessions live in a SQLite database, `~/.local/share/opencode/opencode.db`,
not in files. No rule derives from a path. Recorded as absent until the
tool grows an export, or someone writes the query.
