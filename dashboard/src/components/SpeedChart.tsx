// @author Claude Sonnet 4.6 Anthropic
import { useEffect, useState } from 'react';
import ReactEChartsCore from 'echarts-for-react/esm/core';
import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { RunFilter, DurationPoint } from '../data/DataSource';
import { SqlJsDataSource } from '../data/SqlJsDataSource';

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

interface Props {
  ds: SqlJsDataSource;
  filter: RunFilter;
}

function fmtDuration(s: number): string {
  if (s < 60) return `${s.toFixed(0)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  return rem > 0 ? `${m}m ${rem}s` : `${m}m`;
}

const MODEL_COLORS = [
  '#2a9', '#c80', '#66c', '#a76', '#c6a', '#6a8', '#aa6', '#c33',
  '#48b', '#b84', '#84b', '#4b8', '#b48', '#8b4',
];

export default function SpeedChart({ ds, filter }: Props) {
  const [data, setData] = useState<DurationPoint[]>([]);

  useEffect(() => {
    ds.durationTrend(filter).then(setData).catch(() => setData([]));
  }, [ds, filter]);

  const clean = data.filter((d) => d.model != null && d.avg_duration_s != null);
  if (clean.length === 0) {
    return <p style={{ color: '#666', fontSize: '0.8rem' }}>no speed data</p>;
  }

  const dates = [...new Set(clean.map((d) => d.date))].sort();
  const models = [...new Set(clean.map((d) => d.model))].sort();

  const byModel = new Map<string, Map<string, number>>();
  for (const d of clean) {
    if (!byModel.has(d.model)) byModel.set(d.model, new Map());
    byModel.get(d.model)!.set(d.date, d.avg_duration_s);
  }

  const option: echarts.EChartsCoreOption = {
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const ps = params as { seriesName: string; value: number }[];
        const date = (params as { axisValue: string }[])[0]?.axisValue ?? '';
        return [
          `<b>${date}</b>`,
          ...ps.map((p) => `${p.seriesName}: ${fmtDuration(p.value)}`),
        ].join('<br/>');
      },
    },
    legend: {
      data: models,
      textStyle: { color: '#aaa', fontSize: 10 },
      bottom: 0,
    },
    grid: { left: 60, right: 20, top: 10, bottom: 40 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { color: '#888', fontSize: 10 },
      axisLine: { lineStyle: { color: '#333' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        color: '#888',
        fontSize: 10,
        formatter: (v: number) => fmtDuration(v),
      },
      splitLine: { lineStyle: { color: '#2a2a2a' } },
    },
    series: models.map((model, i) => ({
      name: model,
      type: 'line',
      smooth: true,
      symbol: 'circle',
      symbolSize: 4,
      lineStyle: { color: MODEL_COLORS[i % MODEL_COLORS.length], width: 2 },
      itemStyle: { color: MODEL_COLORS[i % MODEL_COLORS.length] },
      data: dates.map((d) => byModel.get(model)?.get(d) ?? null),
    })),
  };

  return (
    <div style={{ background: '#111', borderRadius: '4px', padding: '0.5rem' }}>
      <ReactEChartsCore echarts={echarts} option={option} style={{ height: 260 }} />
    </div>
  );
}
