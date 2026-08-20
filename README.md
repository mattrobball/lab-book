# Lab Book

An Agent Skills package that turns a repository into a research lab notebook.
The model in the session is the Director: it talks to you, writes briefs,
dispatches workers to do the work, ingests what they return, and keeps the
record. You are the Investigator — you set the questions and decide what
matters.

The record has three parts that never mix. The **notebook** says what happened,
one file per run, written once. **STATUS.md** says what is currently believed,
and gets rewritten freely. **Claims** carry status and provenance, and nothing
counts as a fact until it is one.

## The design principle

Every mechanism here names the failure it prevents. If it cannot name one, it
should not exist.

- **One notebook file per entry, plus a generated index** — prevents the single
  notebook file that grows until nobody reads it and two versions of the
  bottom line drift apart inside it.
- **Claim status only through a script** — prevents a status that was
  hand-edited into a file, believed for weeks, and traceable to nothing.
- **The script commits its own writes** — prevents evidence that exists on
  someone's disk but not in the history, which is a rumour.
- **Replay with exact marker strings** — prevents a worker's report of success
  standing in for success.
- **The discoverer never promotes its own result** — prevents a run grading its
  own homework.
- **Catchup** — prevents "what happened last week?" being answered by grepping
  a hundred run directories.

## Install

One line, any of 40+ coding-agent CLIs:

    npx skills add mattrobball/lab-book

Claude Code can also install it as a plugin:

    /plugin marketplace add mattrobball/lab-book
    /plugin install lab-book@lab-book

Or by hand: copy the `skills/lab-book/` directory into your CLI's skill path.

| CLI | Path |
|---|---|
| Claude Code | `~/.claude/skills/` |
| Codex | `~/.codex/skills/` |
| Cursor | `~/.cursor/skills/` |
| Gemini | `~/.gemini/skills/` |
| Copilot | `~/.copilot/skills/` |
| pi | `~/.pi/agent/skills/` |
| shared, where supported | `~/.agents/skills/` |

For example:

    cp -R skills/lab-book ~/.claude/skills/

Then open a session anywhere and say: **set up a lab here**. The model asks you
five questions about the problem, probes the machine for the agent tools and
subject tools it can actually use, searches the literature on your exact
question, shows you what it found, writes the confirmed list to `lab.json`, and
scaffolds the lab into that repository.

A worked reference instance — a real problem, real runs, real claims, and one
real failure filed the honest way — exists and will be published once it holds
up as an example worth copying.

## Status

Complete and dogfooded: the charter, the two references, the templates, and both
scripts with their test suite (`python3 -m unittest` from
`skills/lab-book/scripts/tests/`).

## Contributing

Issues welcome. For proposed mechanisms, the kit's own rule applies: name the
failure it prevents, or it should not exist.
