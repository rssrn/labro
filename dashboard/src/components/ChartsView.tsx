// @author Claude Sonnet 4.6 Anthropic
import type { RunFilter } from '../data/DataSource';
import { SqlJsDataSource } from '../data/SqlJsDataSource';
import CostTrendChart from './CostTrendChart';
import TokenTrendChart from './TokenTrendChart';
import OutcomeTrendChart from './OutcomeTrendChart';
import BreakdownCharts from './BreakdownCharts';
import EngagementChart from './EngagementChart';
import SpeedChart from './SpeedChart';

interface Props {
  ds: SqlJsDataSource;
  filter: RunFilter;
}

export default function ChartsView({ ds, filter }: Props) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <section>
        <h3 style={{ color: '#aaa', fontSize: '0.9rem', margin: '0 0 0.5rem' }}>Outcomes</h3>
        <OutcomeTrendChart ds={ds} filter={filter} />
      </section>
      <section>
        <h3 style={{ color: '#aaa', fontSize: '0.9rem', margin: '0 0 0.5rem' }}>Breakdowns</h3>
        <BreakdownCharts ds={ds} filter={filter} />
      </section>
      <section>
        <h3 style={{ color: '#aaa', fontSize: '0.9rem', margin: '0 0 0.5rem' }}>Engagement</h3>
        <EngagementChart ds={ds} filter={filter} />
      </section>
      <section>
        <h3 style={{ color: '#aaa', fontSize: '0.9rem', margin: '0 0 0.5rem' }}>Duration</h3>
        <SpeedChart ds={ds} filter={filter} />
      </section>
      <section>
        <h3 style={{ color: '#aaa', fontSize: '0.9rem', margin: '0 0 0.5rem' }}>Cost &amp; Token Trends</h3>
        <CostTrendChart ds={ds} filter={filter} />
        <div style={{ marginTop: '0.75rem' }}>
          <TokenTrendChart ds={ds} filter={filter} />
        </div>
      </section>
    </div>
  );
}
