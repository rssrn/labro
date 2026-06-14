"""ProactiveImprovementTaskSource — autonomous suggestion task source (M7 scope).

When no delegated work is queued, this source fires: the harness creates a
GitHub issue with a standard header and instructs the agent to investigate and
post its findings as a comment.  A randomly selected perspective from
``perspectives.toml`` shapes the agent's approach.

Cap check: if the repo already has >= ``max_open_suggestions`` open issues
labelled ``ai-proactive-suggestion``, this source returns None (skipped).

All subprocess calls use list-form args with shell=False (ARCHITECTURE
line 900; enforced by bandit B602).

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
import logging
import random
import re
import subprocess

from labro.config.schema import (
    PermittedAction,
    PersonaConfig,
    PerspectiveConfig,
    ProjectConfig,
)
from labro.config.schema import (
    ProactiveImprovementSource as ProactiveImprovementSourceConfig,
)
from labro.models import AgentConfig, Task, make_task_id
from labro.task_sources.base import TaskSource

logger = logging.getLogger(__name__)

_AI_PROACTIVE_LABEL = "ai-proactive-suggestion"

# Default permitted actions for proactive runs.  The harness creates the issue
# directly; the agent should comment and optionally open a PR with the fix.
_DEFAULT_PERMITTED_ACTIONS: list[PermittedAction] = [
    PermittedAction.COMMENT_ON_ISSUE,
    PermittedAction.OPEN_PR,
]

_ISSUE_URL_RE = re.compile(r"/issues/(\d+)$")


def _count_open_suggestions(repo: str) -> int:
    """Return the number of open issues labelled ``ai-proactive-suggestion`` in *repo*."""
    result = subprocess.run(  # — list-form args, shell=False
        [
            "gh",
            "api",
            "--paginate",
            f"repos/{repo}/issues?state=open&labels={_AI_PROACTIVE_LABEL}&per_page=100",
        ],
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    )
    items: list[object] = json.loads(result.stdout)
    return len(items)


def _ensure_label(repo: str, label: str) -> None:
    """Create *label* in *repo* if it does not already exist (no-op if it does)."""
    subprocess.run(  # — list-form args, shell=False
        ["gh", "label", "create", label, "--repo", repo, "--force"],
        capture_output=True,
        shell=False,
    )


def _create_issue(repo: str, title: str, body: str) -> tuple[int, str]:
    """Create a GitHub issue and return ``(number, url)``.

    ``gh issue create`` prints the new issue URL to stdout; the number is
    extracted from the URL path.
    """
    _ensure_label(repo, _AI_PROACTIVE_LABEL)
    result = subprocess.run(  # — list-form args, shell=False
        [
            "gh",
            "issue",
            "create",
            "--repo",
            repo,
            "--title",
            title,
            "--body",
            body,
            "--label",
            _AI_PROACTIVE_LABEL,
        ],
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    )
    url = result.stdout.strip()
    m = _ISSUE_URL_RE.search(url)
    if not m:
        raise ValueError(f"could not parse issue number from gh output: {url!r}")
    return int(m.group(1)), url


def _build_issue_body(
    perspective_name: str | None,
    agent_slug: str,
    perspective_prompt: str | None = None,
) -> str:
    """Return the standard issue body header for a proactive suggestion."""
    lines: list[str] = [
        "<!-- Labro proactive suggestion — do not edit this header -->",
        "This is an autonomous proactive suggestion requested by Labro.",
    ]
    if perspective_name:
        lines.append(f"**Perspective:** {perspective_name}")
    if perspective_prompt:
        lines.append(f"> {perspective_prompt}")
    lines += [
        "",
        "---",
        "",
        "Agent findings will be posted as a comment below.",
        "",
        f"**Agent:** `{agent_slug}`",
    ]
    return "\n".join(lines)


class ProactiveImprovementTaskSource(TaskSource):
    """Task source that creates a proactive improvement suggestion issue."""

    def __init__(
        self,
        source_config: ProactiveImprovementSourceConfig,
        personas: dict[str, PersonaConfig],
        perspectives: dict[str, PerspectiveConfig],
    ) -> None:
        self._cfg = source_config
        self._personas = personas
        self._perspectives = perspectives

    def fetch_task(
        self,
        project: ProjectConfig,
        defaults_model: list[str],
        defaults_max_turns: int,
        defaults_timeout_s: int,
        defaults_max_comments: int,
    ) -> tuple[Task, AgentConfig] | None:
        # ── Cap check ──────────────────────────────────────────────────────────
        try:
            open_count = _count_open_suggestions(project.repo)
        except subprocess.CalledProcessError as exc:
            logger.warning("proactive-improvement: cap check failed for %s: %s", project.repo, exc)
            return None

        if open_count >= self._cfg.max_open_suggestions:
            logger.info(
                "proactive-improvement: skipping %s — %d open suggestion(s) >= cap %d",
                project.repo,
                open_count,
                self._cfg.max_open_suggestions,
            )
            return None

        # ── Perspective selection ───────────────────────────────────────────────
        chosen_name: str | None = None
        perspective_prompt: str | None = None

        if self._perspectives:
            candidate_names = self._cfg.perspectives or list(self._perspectives.keys())
            # Guard against a misconfigured perspectives list with no valid names.
            valid = [n for n in candidate_names if n in self._perspectives]
            if valid:
                chosen_name = random.choice(valid)  # noqa: S311
                perspective_prompt = self._perspectives[chosen_name].prompt

        # ── Resolve config overrides (source → project → defaults) ─────────────
        model_slugs: list[str] = self._cfg.model or project.model or defaults_model
        permitted_actions: list[PermittedAction] = (
            self._cfg.permitted_actions or project.permitted_actions or _DEFAULT_PERMITTED_ACTIONS
        )
        persona_prompt: str | None = None
        if self._cfg.persona and self._cfg.persona in self._personas:
            persona_prompt = self._personas[self._cfg.persona].prompt

        max_turns = defaults_max_turns
        timeout_s = defaults_timeout_s

        # ── Build agent config (needed for issue body slug) ────────────────────
        agent_cfg = AgentConfig.from_slug_list(
            model_slugs,
            max_turns=max_turns,
            timeout_s=timeout_s,
            permitted_actions=permitted_actions,
        )

        # ── Create GitHub issue ────────────────────────────────────────────────
        title = (
            f"Labro proactive suggestion — {chosen_name}"
            if chosen_name
            else "Labro proactive suggestion"
        )
        body = _build_issue_body(chosen_name, agent_cfg.slug, perspective_prompt)

        try:
            item_number, item_url = _create_issue(project.repo, title, body)
        except (subprocess.CalledProcessError, KeyError, ValueError) as exc:
            logger.warning(
                "proactive-improvement: failed to create issue in %s: %s", project.repo, exc
            )
            return None

        # ── Build Task ─────────────────────────────────────────────────────────
        if chosen_name:
            description = (
                f"Apply the **{chosen_name}** perspective (see the Perspective section below) "
                f"to this project. "
                f"Use whatever tools and sources are useful — repo exploration, web searches, "
                f"external docs — then post your findings as a comment on this issue. "
                f"Limit your suggestions to the **1-5 highest-priority** items only; "
                f"do not list every possible improvement. "
                f"Once you know what your suggestion is, rename the issue to a specific, "
                f'descriptive title using `gh issue edit {item_number} --title "..." '
                f"--repo {project.repo}`."
            )
        else:
            description = (
                "Identify the most valuable improvement you can suggest for this project. "
                "Use whatever tools and sources are useful — repo exploration, web searches, "
                "external docs — then post your findings as a comment on this issue. "
                "Limit your suggestions to the **1-5 highest-priority** items only; "
                "do not list every possible improvement. "
                f"Once you know what your suggestion is, rename the issue to a specific, "
                f'descriptive title using `gh issue edit {item_number} --title "..." '
                f"--repo {project.repo}`."
            )

        task = Task(
            task_id=make_task_id(),
            source="proactive-improvement",
            description=description,
            permitted_actions=permitted_actions,
            repo=project.repo,
            item_type="issue",
            item_number=item_number,
            item_url=item_url,
            source_label=None,
            done_label=None,
            grafana_rule_uid=None,
            persona_prompt=persona_prompt,
            perspective_prompt=perspective_prompt,
            chosen_perspective=chosen_name,
            source_description=(
                f"💡 {chosen_name.replace('-', ' ').title()}" if chosen_name else None
            ),
        )

        return task, agent_cfg
