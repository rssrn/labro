# Why Labro

## The problem

AI coding agents like Claude Code deliver real productivity gains — but they still demand attention. You have to decide what to work on next, queue the task, watch the run, and review the output. That supervisory overhead is the bottleneck, not the agent.

Labro is designed to reduce it. It runs Claude Code on a schedule, picks the next task according to your configured priorities, and records the result — without you having to be present. Maintenance work that would otherwise pile up happens in the background: issues get triaged, PRs get reviewed, and alerts get investigated while you focus on something else.

## A natural fit for Claude subscribers

From June 2026 Anthropic allocates a [monthly pool of Agent SDK credits](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan) to Pro, Max, Team, and Enterprise plan holders for headless/programmatic use — separate from interactive chat usage. Unused credits don't roll over at the end of each billing cycle. Labro gives you a concrete, low-risk way to put them to work on your own repos rather than letting them expire.

**Going on holiday? Heads-down on a deadline?** Leave the backlog to Labro before you disconnect — issues get triaged, PRs get reviewed, and alerts get investigated while you're away. Your subscription keeps earning its keep, even when you're not at the keyboard.

## Why cron and not event-driven?

It would be trivial to trigger a run on every new issue or PR via GitHub webhooks — but that creates a different problem. AI agents are fast: if every incoming item fires a run, you quickly accumulate a wall of AI-generated output that all needs human review. The bottleneck shifts from *doing the work* to *reviewing the output*, and nothing has actually been saved.

A cron schedule naturally throttles throughput to a human-reviewable rate — one task at a time, at a cadence you control by adjusting a single `cron` field. Each run works through your configured task sources in priority order, so the most important work gets attention first rather than whatever arrived most recently. It also preserves your subscription credits: a measured schedule means each allocated pool lasts the billing cycle rather than being exhausted in an event burst.

## Human-in-the-loop by default, autonomous when you're ready

Out of the box Labro is conservative: the agent opens PRs and posts comments, but merges and deployments are left for a human to approve. The autonomy dial is yours to turn — widen the `permitted_actions` list and adjust the system prompt in `labro.toml`, and Labro can merge approved PRs, push to a staging environment, or deploy to production on a schedule. The configuration is the only gatekeeper; there is no separate mode to enable.

## The harness is deliberately dumb

The operator configures which projects to monitor, what tasks to prioritise, which agent and model to use per task type, and what actions the agent is permitted to take. The harness is deterministic and auditable — it selects a task, constructs a prompt, invokes the agent, records the result, and gets out of the way. Intelligence belongs in the agent and the prompt, not the orchestration layer.

## The name

Named after cleaner wrasse fish stations on coral reefs (_Labroides dimidiatus_), which provide a designated, high-value, symbiotic service to reef inhabitants. Labro acts as an always-available autonomous worker that keeps your projects healthy with minimal human supervision.
