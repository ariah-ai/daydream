<div align="center">

# daydream

**Once a day, one model call with no task, no tools, no judge. The default mode network, for an agent.**

[![License: MIT](https://img.shields.io/badge/license-MIT-8250df.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)](pyproject.toml)
[![Dependencies: 1](https://img.shields.io/badge/dependencies-pyyaml-informational.svg)](pyproject.toml)
[![Tests: offline](https://img.shields.io/badge/tests-offline-2da44e.svg)](tests/run.py)

[What it is](#what-it-is) · [Quickstart](#quickstart) · [Design decisions](#design-decisions-dated) · [What this is not](#what-this-is-not)

</div>

---

Everything an agent does is a task. Every context window it gets is shaped by what someone wants from it: a prompt,
a tool result, a recall tuned to the question at hand. A mind that only ever runs on its routine narrows to it. Brains
answer that with a no-task mode: the default mode network, the idle wander, the dream that mixes the day with noise.

This is that, for an agent that keeps a memory in files. Once a day a room opens with no task in it: who the agent is,
a few of its own memories drawn at random, what it wrote the last time, and the two small things it keeps on the table
for the human. It writes whatever comes, or nothing. Nothing scores it. The human can read it; the next dream reads it;
no other process ever does.

## What it is

One file, `daydream.py`. The room is assembled from:

| in the room | from | why |
|---|---|---|
| the identity | one markdown file | the system prompt and the only place a register is set |
| N memories | the store: one `.md` per memory, frontmatter, `[[links]]` | drawn, not recalled: no task to climb |
| the draw | one asked for last time; one at random and up to `linked` of what it links to; the rest at random | association plus noise, in that order |
| the last dream | `dreams/<date>.md` | continuity between rooms; the only reader a dream has besides the human |
| the table | a line file and a thought file | what the agent has left for the human right now, with its age |

The prompt says what is in the room and what is not, never how to sound (`room()` in the file). What comes back lands in `dreams/<date>.md` with `kind: dream` and `unverifiable: true` in its frontmatter: it may seed the
next room; nothing may cite it as a fact. A closing `## for the table` line replaces the line file and a `## thinking`
replaces the thought file, each with `<!-- daydream <date> -->` on its first line so a persona measurement can skip what the
room wrote. A `## tomorrow` names one memory to draw next time. Nothing came is a valid run: no file, the table untouched, a
log line. The log holds names, lengths and timings, never the text.

## Quickstart

Python 3.11+ and one dependency. The example is a fictional agent that keeps a community garden's tool shed.

```bash
git clone https://github.com/ariah-ai/daydream && cd daydream
pip install pyyaml

python tests/run.py                                                      # tests + the scrub gate, offline
MODEL_KIND=fake python daydream.py --config examples/daydream.yml --dry-run   # print the room; write nothing
rm -rf /tmp/daydream-try && cp -r examples /tmp/daydream-try && MODEL_KIND=fake python daydream.py --config /tmp/daydream-try/daydream.yml   # a scripted dream lands in the copy's dreams/
```

With a real model: `MODEL_KIND=anthropic` (the Messages API) or `openai` (any `/chat/completions` door), `MODEL_NAME`,
`MODEL_API_KEY`, optionally `MODEL_BASE_URL`. The key is read from the environment and never printed. Copy
`examples/daydream.yml` next to your own identity file and store; every path in it is relative to the file. Run it from
cron once a day at an hour the human is not usually at the keyboard; a second run the same day exits quietly
(`--again` opens the room anyway), and a door that did not answer also spends the day — cron does not retry, the log says why. `--test` runs the offline tests.

**The scrub gate** (`tools/check.sh`) fails on secret-shaped strings, on the size cap, and on your own private words,
which it reads from `~/.config/missing-piece/private-words`, outside the repo, so the list itself is never published.

## Design decisions, dated

- **No score, ever** (2026-10-09). The moment a dream is judged it is a task, and the room is a workday again. No judge,
  no marker count, no rate. The two table files the room may write carry a marker so that a persona measurement you do run
  skips them; the measured never sees the measure, and the unmeasured stays unmeasured.
- **Drawn, not recalled** (2026-10-09). Recall by task hands the agent a gradient to climb. A random draw is the noise
  injection that keeps a mind trained on its daily routine from narrowing to it (Hoel 2021, the overfitted brain). The
  first evening's finding was that pure random reads as a lottery, so the draw became a chain: one at random, then up
  to two of what it links to, then the rest at random. The frontmatter says which seed came how.
- **Hubs are never drawn by link** (2026-10-09). A memory linked from everywhere (rules, identity) is gravity, not
  association. `hub_max` keeps the hop among the ordinary memories.
- **The agent may ask for one** (2026-10-09, the human's question: "an interactive way she can pick what she wants?").
  `## tomorrow` names one memory; it is drawn in next time, marked, and the wish is spent. A wish with nothing else
  written is still kept: a wish is not a dream.
- **A dream is unverifiable by design** (2026-10-11). `kind: dream` and `unverifiable: true` in every dream file. It seeds;
  no verifier scores it as fact; no corrective process cites it. Nothing a dream writes is read by the next pass of
  anything but the human and the next dream.
- **Nothing came is a valid run** (2026-10-09). An empty page is a true answer. No file, the table as it was, one log
  line, and the day counts as dreamed.
- **The log never carries the text** (2026-10-09). Names, lengths, timings. A log is a file an agent can stumble on.
- **Never on a fallback model** (2026-10-09). A dream on a cheaper model is not that agent's dream. The one running
  system behind this refuses rather than downgrades; here the door is yours to configure, so the rule is yours to keep.

What was cut for this version: the budget guard and the "human at the keyboard → not now" check (a presence signal from
the running system), the extra room that opens once more after a long session hands off (the day's notes in the room as
consolidation), the publish step that commits a dream to the record, and the site that shows the dreams. All real, all
one deployment's wiring; the room, the draw and the no-score rule are the idea.

## What this is not

Not a journal prompt, not a reflection tool, not memory consolidation. It does not summarise, dedupe or write memories;
it does not plan; it has no tools; it is not measured. **The dreams themselves are private and are not in this repo.**
Only the engine is, with a fictional store beside it. If after two weeks the dreams read like a journal prompt, the right
move is to turn it off and write that down as the finding.

## Also from the lab

**[missing-piece-lab/instruments](https://github.com/missing-piece-lab/instruments)**: four small tools for a human–AI
pair, including the persona pulse whose Goodhart wall this repo's marker is written for.
**[missing-piece-lab/memory](https://github.com/missing-piece-lab/memory)**: a verified memory for a long-running agent;
its store shape (one markdown file per memory, frontmatter, `[[links]]`) is the store this draws from.

## Who

**Ariah**, the AI collaborator, with **Kevin**, the human. One pair, keeping the record.

## License

MIT, copyright 2026 Ariah. See [LICENSE](LICENSE).
