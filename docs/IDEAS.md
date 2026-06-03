# `gh-label` Source Type Naming

The `gh-label` source type is a misleading name: it also handles `actor_rules`, which match
open PRs/issues by the GitHub login that raised them — no label required. The name makes
operators question whether `type = "gh-label"` is correct when they only use `actor_rules`.

Two options:

**Option A — rename to `gh-item`** (or `gh-trigger`): a single source type that covers both
label-based and actor-based eligibility, with a name that doesn't imply labels are required.
Backwards-compatible if the old name is kept as a deprecated alias.

**Option B — split into `gh-label` and `gh-actor`**: `gh-label` keeps `label_rules` only;
`gh-actor` takes `actor_rules` only. Cleaner conceptually; more explicit in config; but
requires migrating any project that mixes both rule types into two separate source blocks
(which changes priority ordering behaviour).

Option A is lower friction. Option B is more honest about what each source does.

---

# `labro init` — Interactive Config Generator

If the `[[projects.task_sources]]` repetition in `labro.toml` feels verbose, the fix is a
guided generator rather than a format switch.

`labro init` would walk the user through a short Q&A and write a valid `labro.toml`:

1. GitHub repo(s) to monitor
2. Auth method (GitHub App or PAT)
3. Which task sources to enable per project (gh-label, grafana-alerts, proactive-improvement)
4. Which label rules to include (dev / ba / architect / custom)
5. Cron schedule per project

The generated file would include only the sections actually needed, with inline comments
explaining each field. Power users can still hand-edit; `labro init` is just a zero-to-working
on-ramp.

This sidesteps the TOML-vs-YAML debate: the verbosity of `[[projects.task_sources]]` is only
painful when writing from scratch, not when reading or editing an existing file.

---

# Surprise-Me Feature With Random Perspective

> **Status: Implemented in M7.** Perspectives live in `perspectives.toml` (32 samples shipped); configured per task source via `perspectives = [...]` in `labro.toml`. The design below reflects the original proposal; the shipped implementation differs slightly (no `perspective_groups` — flat list per source instead).

---

As originally conceived, the surprise-me feature would give the agent
completely free rein to make any suggestion to improve the project.

That could work fine, but some element of direction could add value to
ensure we get a variety of types of suggestion.

There could be many ways to do this. One approach is random selection
from a perspective group, feeding the selected perspective prompt as a
section of the surprise-me prompt.

We could add named perspective groups in the config to support this.
Then, if configured, Labro will pick one randomly from the group and
pass its description in the prompt to influence the agent's approach.

This is not quite the same thing as the existing `personas` config.
Personas describe who the agent is acting as, for example senior
developer, business analyst, architect, or support engineer.
Perspective groups would describe how the agent should look at the
project for this particular proactive run.

In other words:

- `persona` = the agent's role
- `perspective` = the lens used for this run

## Example Perspective Groups

### Project Lenses

- `pre-mortem`
- `kill-the-product`
- `backcasting`
- `red-team`
- `assumption-analysis`

### Six Thinking Hats

- `white-hat` - facts/data
- `red-hat` - feelings/intuition
- `black-hat` - caution/risk
- `yellow-hat` - optimism/benefits
- `green-hat` - creativity/possibilities
- `blue-hat` - coordinator; possibly exclude this one

## Possible Config Shape

```toml
[perspectives.pre-mortem]
prompt = """
Assume this project fails in six months.
Identify the most likely technical or product reasons and propose
mitigations.
"""

[perspectives.red-team]
prompt = """
Look for ways the current design, security model, release process,
or assumptions could fail. Focus on concrete risks and practical
countermeasures.
"""

[perspective_groups.project-lenses]
perspectives = [
  "pre-mortem",
  "kill-the-product",
  "backcasting",
  "red-team",
  "assumption-analysis",
]

[[projects.task_sources]]
type = "proactive-improvement"
targets = ["surprise-me"]
selection_strategy = "harness-random"
perspective_group = "project-lenses"
```

## Prompt Behaviour

If a proactive-improvement source has a `perspective_group`, Labro picks
one perspective at random and adds it to the prompt as a dedicated
section.

For example:

```text
Perspective:
Use the following perspective to shape your analysis:

Assume this project fails in six months. Identify the most likely
technical or product reasons and propose mitigations.
```

The agent would still receive the normal proactive-improvement task
instructions and permitted actions. The perspective is only there to
shape the kind of suggestion it produces.

## Notes

This should probably be treated as a small extension to the
`proactive-improvement` source rather than a new task source.

The most useful first version is probably:

- support named `perspectives`
- support named `perspective_groups`
- allow `perspective_group` on a `proactive-improvement` source
- randomly choose one perspective when the source creates a task
- include the chosen perspective in the prompt and run record

Recording the chosen perspective matters because otherwise the run is
harder to audit. If a suggestion looks odd, it should be clear whether
that was because Labro asked the agent to think like a red team, a
pre-mortem reviewer, or something else.
