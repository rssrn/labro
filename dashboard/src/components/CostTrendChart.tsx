// @author Claude Sonnet 4.6 Anthropic
import { useEffect, useState } from 'react';
import ReactEChartsCore from 'echarts-for-react/esm/core';
import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { RunFilter, TrendPoint } from '../data/DataSource';
import { SqlJsDataSource } from '../data/SqlJsDataSource';

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

interface Props {
  ds: SqlJsDataSource;
  filter: RunFilter;
}

export default function CostTrendChart({ ds, filter }: Props) {
  const [data, setData] = useState<TrendPoint[]>([]);

  useEffect(() => {
    ds.trend(filter).then(setData).catch(() => setData([]));
  }, [ds, filter]);

  if (data.length === 0) {
    return <p style={{ color: '#666', fontSize: '0.8rem' }}>no cost data</p>;
  }

  const option: echarts.EChartsCoreOption = {
    tooltip: {
      trigger: 'axis',
      theme: 'dark',
      formatter: (params: unknown) => {
        const p = (params as { axisValue: string; value: number }[])[0];
        return `${p.axisValue}<br/>$${p.value.toFixed(4)}`;
      },
    },
    grid: { left: 60, right: 20, top: 10, bottom: 30 },
    xAxis: {
      type: 'category',
      data: data.map((d) => d.date),
      axisLabel: { color: '#888', fontSize: 10 },
      axisLine: { lineStyle: { color: '#333' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        color: '#888',
        fontSize: 10,
        formatter: (v: number) => `$${v.toFixed(2)}`,
      },
      splitLine: { lineStyle: { color: '#2a2a2a' } },
    },
    series: [{
      type: 'line',
      data: data.map((d) => d.cost_usd),
      smooth: true,
      symbol: 'circle',
      symbolSize: 5,
      lineStyle: { color: '#2a9', width: 2 },
      itemStyle: { color: '#2a9' },
      areaStyle: { color: 'rgba(34, 170, 153, 0.15)' },
    }],
  };

  return (
    <div style={{ background: '#111', borderRadius: '4px', padding: '0.5rem' }}>
      <ReactEChartsCore echarts={echarts} option={option} style={{ height: 200 }} />
    </div>
  );
}
