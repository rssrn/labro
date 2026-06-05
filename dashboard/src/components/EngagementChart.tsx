// @author Claude Sonnet 4.6 Anthropic
import { useEffect, useState } from 'react';
import ReactEChartsCore from 'echarts-for-react/esm/core';
import * as echarts from 'echarts/core';
import { BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { RunFilter, EngagementRow } from '../data/DataSource';
import { SqlJsDataSource } from '../data/SqlJsDataSource';

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

interface Props {
  ds: SqlJsDataSource;
  filter: RunFilter;
}

const STATE_COLORS: Record<string, string> = {
  merged: '#2a9',
  closed_completed: '#2a9',
  closed_not_planned: '#888',
  closed_unmerged: '#c80',
  open: '#66c',
};

const STATE_LABELS: Record<string, string> = {
  merged: 'Merged',
  closed_completed: 'Completed',
  closed_not_planned: 'Not planned',
  closed_unmerged: 'Unmerged',
  open: 'Open',
};

export default function EngagementChart({ ds, filter }: Props) {
  const [data, setData] = useState<EngagementRow[]>([]);

  useEffect(() => {
    ds.engagementSignals(filter).then(setData).catch(() => setData([]));
  }, [ds, filter]);

  if (data.length === 0) {
    return <p style={{ color: '#666', fontSize: '0.8rem' }}>no engagement data</p>;
  }

  const labels = data.map((r) => STATE_LABELS[r.outcome_state] ?? r.outcome_state);
  const counts = data.map((r) => r.count);
  const colors = data.map((r) => STATE_COLORS[r.outcome_state] ?? '#aaa');

  const totalThumbsUp = data.reduce((s, r) => s + r.thumbs_up, 0);
  const totalThumbsDown = data.reduce((s, r) => s + r.thumbs_down, 0);
  const totalFollowUp = data.reduce((s, r) => s + r.follow_up_commits, 0);

  const option: echarts.EChartsCoreOption = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: unknown) => {
        const p = (params as { name: string; value: number }[])[0];
        return `${p.name}: ${p.value}`;
      },
    },
    grid: { left: 50, right: 20, top: 10, bottom: 30 },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#ccc', fontSize: 10 },
      axisLine: { lineStyle: { color: '#333' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#888', fontSize: 10 },
      splitLine: { lineStyle: { color: '#2a2a2a' } },
    },
    series: [{
      type: 'bar',
      data: counts.map((v, i) => ({ value: v, itemStyle: { color: colors[i] } })),
      barMaxWidth: 40,
    }],
  };

  return (
    <div>
      <div style={{ background: '#111', borderRadius: '4px', padding: '0.5rem' }}>
        <ReactEChartsCore echarts={echarts} option={option} style={{ height: 200 }} />
      </div>
      <div style={{ display: 'flex', gap: '1.5rem', marginTop: '0.5rem', color: '#aaa', fontSize: '0.82rem' }}>
        <span>👍 {totalThumbsUp}</span>
        <span>👎 {totalThumbsDown}</span>
        <span>follow-up commits: {totalFollowUp}</span>
      </div>
    </div>
  );
}
