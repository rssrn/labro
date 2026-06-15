// @author Claude Sonnet 4.6 Anthropic
import type { Run } from '../data/DataSource';

export function fmtCost(usd: number | null, precision = 2): string {
  if (usd == null) return '—';
  if (usd <= 0) return `$${(0).toFixed(precision)}`;
  if (usd < 0.01) return '<$0.01';
  return `$${usd.toFixed(precision)}`;
}

export function fmtModel(provider: string | null, model: string | null): string {
  if (!model) return "[agent's internal default]";
  const short = model.replace(/^claude-/, '');
  return provider ? `${provider}/${short}` : short;
}

/** Returns the display label for the source column, swapping 🎭→💡 on thumbs-up proactive runs. */
export function sourceLabel(run: Run): string {
  const label = run.source_description ?? run.task_source ?? '—';
  const thumbsUp = (run.thumbs_up ?? 0) > 0;
  return thumbsUp ? label.replace('🎭', '💡') : label;
}

/** Accessible text for the source cell (strips leading emoji, prefixes task_source). */
export function sourceAriaLabel(run: Run): string {
  const desc = run.source_description;
  const text = desc ? desc.replace(/^\S+\s*/, '').trim() : null;
  const base = text ? `${run.task_source ?? '—'}: ${text}` : (run.task_source ?? '—');
  return (run.thumbs_up ?? 0) > 0 ? `${base} (highly rated)` : base;
}
