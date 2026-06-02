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
