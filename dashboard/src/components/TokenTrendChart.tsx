// @author Claude Sonnet 4.6 Anthropic
import { useEffect, useState } from 'react';
import ReactEChartsCore from 'echarts-for-react/esm/core';
import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { RunFilter, TrendPoint } from '../data/DataSource';
import { SqlJsDataSource } from '../data/SqlJsDataSource';

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

interface Props {
  ds: SqlJsDataSource;
  filter: RunFilter;
}

function fmt(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}

const COLORS = ['#2a9', '#c80', '#888', '#66c'];
const LABELS = ['input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens'];
const NAMES = ['Input', 'Output', 'Cache read', 'Cache write'];

export default function TokenTrendChart({ ds, filter }: Props) {
  const [data, setData] = useState<TrendPoint[]>([]);

  useEffect(() => {
    ds.trend(filter).then(setData).catch(() => setData([]));
  }, [ds, filter]);

  if (data.length === 0) {
    return <p style={{ color: '#666', fontSize: '0.8rem' }}>no token data</p>;
  }

  const option: echarts.EChartsCoreOption = {
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const ps = params as { seriesName: string; value: number }[];
        const date = (params as { axisValue: string }[])?.length ? (params as { axisValue: string }[])[0].axisValue : '';
        return [
          `<b>${date}</b>`,
          ...ps.map((p) => `${p.seriesName}: ${fmt(p.value)}`),
        ].join('<br/>');
      },
    },
    legend: {
      data: NAMES,
      textStyle: { color: '#aaa', fontSize: 10 },
      bottom: 0,
    },
    grid: { left: 60, right: 20, top: 10, bottom: 40 },
    xAxis: {
      type: 'category',
      data: data.map((d) => d.date),
      axisLabel: { color: '#888', fontSize: 10 },
      axisLine: { lineStyle: { color: '#333' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#888', fontSize: 10, formatter: fmt },
      splitLine: { lineStyle: { color: '#2a2a2a' } },
    },
    series: NAMES.map((name, i) => ({
      name,
      type: 'line',
      stack: 'tokens',
      areaStyle: { color: COLORS[i] + '44' },
      lineStyle: { color: COLORS[i], width: 1 },
      itemStyle: { color: COLORS[i] },
      symbol: 'none',
      data: data.map((d) => d[LABELS[i] as keyof TrendPoint] as number),
    })),
  };

  return (
    <div style={{ background: '#111', borderRadius: '4px', padding: '0.5rem' }}>
      <ReactEChartsCore echarts={echarts} option={option} style={{ height: 220 }} />
    </div>
  );
}
