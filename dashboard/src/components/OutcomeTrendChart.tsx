// @author Claude Sonnet 4.6 Anthropic
import { useEffect, useState } from 'react';
import ReactEChartsCore from 'echarts-for-react/esm/core';
import * as echarts from 'echarts/core';
import { BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { RunFilter, TrendPoint } from '../data/DataSource';
import { SqlJsDataSource } from '../data/SqlJsDataSource';
import { OUTCOME_COLOR } from '../constants';

echarts.use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

interface Props {
  ds: SqlJsDataSource;
  filter: RunFilter;
}

const OUTCOMES = ['success', 'failure', 'partial', 'skipped'] as const;

export default function OutcomeTrendChart({ ds, filter }: Props) {
  const [data, setData] = useState<TrendPoint[]>([]);

  useEffect(() => {
    ds.trend(filter).then(setData).catch(() => setData([]));
  }, [ds, filter]);

  if (data.length === 0) {
    return <p style={{ color: '#666', fontSize: '0.8rem' }}>no outcome data</p>;
  }

  const option: echarts.EChartsCoreOption = {
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const ps = params as { seriesName: string; value: number }[];
        const date = (params as { axisValue: string }[])[0].axisValue;
        return [
          `<b>${date}</b>`,
          ...ps.map((p) => `${p.seriesName}: ${p.value}`),
        ].join('<br/>');
      },
    },
    legend: {
      data: OUTCOMES.map((o) => o.charAt(0).toUpperCase() + o.slice(1)),
      textStyle: { color: '#aaa', fontSize: 10 },
      bottom: 0,
    },
    grid: { left: 50, right: 20, top: 10, bottom: 40 },
    xAxis: {
      type: 'category',
      data: data.map((d) => d.date),
      axisLabel: { color: '#888', fontSize: 10 },
      axisLine: { lineStyle: { color: '#333' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#888', fontSize: 10 },
      splitLine: { lineStyle: { color: '#2a2a2a' } },
    },
    series: OUTCOMES.map((o) => ({
      name: o.charAt(0).toUpperCase() + o.slice(1),
      type: 'bar',
      stack: 'outcomes',
      barWidth: '80%',
      itemStyle: { color: OUTCOME_COLOR[o] },
      data: data.map((d) => d[o]),
    })),
  };

  return (
    <div style={{ background: '#111', borderRadius: '4px', padding: '0.5rem' }}>
      <ReactEChartsCore echarts={echarts} option={option} style={{ height: 220 }} />
    </div>
  );
}
