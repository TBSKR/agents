import { Card, Badge } from '../ui';
import type { Opportunity } from '../../types';

interface TopOpportunitiesProps {
  opportunities: Opportunity[];
  loading?: boolean;
}

export function TopOpportunities({ opportunities, loading }: TopOpportunitiesProps) {
  const formatReturn = (value: number | undefined) => {
    if (value === undefined) return 'N/A';
    return value.toFixed(1) + '%';
  };

  const formatLiquidity = (value: number) => {
    if (value >= 1000) {
      return '$' + (value / 1000).toFixed(1) + 'K';
    }
    return '$' + value.toFixed(0);
  };

  return (
    <Card>
      <h3 className="text-lg font-semibold mb-4">Top Opportunities</h3>
      <div className="space-y-3">
        {loading ? (
          <div className="text-text-secondary text-center py-4">
            Scanning markets...
          </div>
        ) : opportunities.length === 0 ? (
          <div className="text-text-secondary text-center py-4">
            No opportunities found
          </div>
        ) : (
          opportunities.slice(0, 5).map((o, i) => (
            <div key={o.id || i} className="p-3 bg-background rounded-lg">
              <div className="flex justify-between items-start gap-2">
                <span className="font-medium truncate flex-1" title={o.name}>
                  {o.name}
                </span>
                <span className="text-profit font-mono shrink-0">
                  {formatReturn(o.annualized_return || o.edge_pct)}
                </span>
              </div>
              <div className="flex justify-between text-sm text-text-secondary mt-1">
                <Badge>{o.strategy}</Badge>
                <span>{formatLiquidity(o.liquidity)} liq</span>
              </div>
            </div>
          ))
        )}
      </div>
    </Card>
  );
}
