// @author Claude Sonnet 4.6 Anthropic
import { useEffect, useState } from 'react';
import ReactEChartsCore from 'echarts-for-react/esm/core';
import * as echarts from 'echarts/core';
import { BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { RunFilter, BreakdownEntry } from '../data/DataSource';
import { SqlJsDataSource } from '../data/SqlJsDataSource';

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

interface Props {
  ds: SqlJsDataSource;
  filter: RunFilter;
}

const MUTED = ['#2a9', '#c80', '#66c', '#888', '#a76', '#c6a', '#6a8', '#aa6'];

function HorizontalBar({ title, data }: { title: string; data: BreakdownEntry[] }) {
  if (data.length === 0) return null;

  const labels = data.map((d) => d.label ?? '(none)').reverse();
  const values = data.map((d) => d.count).reverse();

  const option: echarts.EChartsCoreOption = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: unknown) => {
        const p = (params as { name: string; value: number }[])[0];
        return `${p.name}: ${p.value}`;
      },
    },
    grid: { left: 140, right: 50, top: 5, bottom: 5 },
    xAxis: {
      type: 'value',
      axisLabel: { color: '#888', fontSize: 10 },
      splitLine: { lineStyle: { color: '#2a2a2a' } },
    },
    yAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#ccc', fontSize: 10, overflow: 'truncate', width: 120 },
      axisLine: { lineStyle: { color: '#333' } },
    },
    series: [{
      type: 'bar',
      data: values.map((v, i) => ({ value: v, itemStyle: { color: MUTED[i % MUTED.length] } })),
      barMaxWidth: 20,
    }],
  };

  return (
    <div style={{ flex: '1 1 250px', minWidth: '200px' }}>
      <h4 style={{ color: '#aaa', fontSize: '0.82rem', margin: '0 0 0.25rem' }}>{title}</h4>
      <ReactEChartsCore echarts={echarts} option={option} style={{ height: Math.max(80, labels.length * 28) }} />
    </div>
  );
}

export default function BreakdownCharts({ ds, filter }: Props) {
  const [modelData, setModelData] = useState<BreakdownEntry[]>([]);
  const [taskSourceData, setTaskSourceData] = useState<BreakdownEntry[]>([]);
  const [perspectiveData, setPerspectiveData] = useState<BreakdownEntry[]>([]);

  useEffect(() => {
    Promise.all([
      ds.modelBreakdown(filter),
      ds.taskSourceBreakdown(filter),
      ds.perspectiveBreakdown(filter),
    ]).then(([m, t, p]) => {
      setModelData(m);
      setTaskSourceData(t);
      setPerspectiveData(p);
    }).catch(() => {
      setModelData([]);
      setTaskSourceData([]);
      setPerspectiveData([]);
    });
  }, [ds, filter]);

  const hasAny = modelData.length > 0 || taskSourceData.length > 0 || perspectiveData.length > 0;
  if (!hasAny) return null;

  return (
    <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
      <HorizontalBar title="Model" data={modelData} />
      <HorizontalBar title="Task source" data={taskSourceData} />
      <HorizontalBar title="Perspective" data={perspectiveData} />
    </div>
  );
}
