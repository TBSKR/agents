import { Card, Badge } from '../ui';
import { STRATEGY_INFO } from '../../types';
import type { StrategyType } from '../../types';

interface StrategyData {
  name: StrategyType;
  allocated: number;
  pnl: number;
  trades: number;
}

interface ActiveStrategiesProps {
  strategies: string[];
  botStatus: string;
}

export function ActiveStrategies({ strategies, botStatus }: ActiveStrategiesProps) {
  // For now, show active strategies with placeholder data
  const strategyData: StrategyData[] = strategies.map((s) => ({
    name: s as StrategyType,
    allocated: Math.round(Math.random() * 500),
    pnl: Math.round((Math.random() - 0.3) * 100) / 10,
    trades: Math.floor(Math.random() * 10),
  }));

  return (
    <Card>
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Active Strategies</h3>
        <Badge
          variant={botStatus === 'running' ? 'success' : botStatus === 'scanning' ? 'warning' : 'default'}
        >
          {botStatus.toUpperCase()}
        </Badge>
      </div>
      <div className="space-y-3">
        {strategyData.length === 0 ? (
          <div className="text-text-secondary text-center py-4">
            No strategies active
          </div>
        ) : (
          strategyData.map((s) => (
            <div
              key={s.name}
              className="flex justify-between items-center p-3 bg-background rounded-lg"
            >
              <div>
                <span className="font-medium">
                  {STRATEGY_INFO[s.name]?.label || s.name}
                </span>
                <span className="text-text-secondary text-sm ml-2">
                  ${s.allocated}
                </span>
              </div>
              <span
                className={`font-mono ${
                  s.pnl >= 0 ? 'text-profit' : 'text-loss'
                }`}
              >
                {s.pnl >= 0 ? '+' : ''}
                {s.pnl}%
              </span>
            </div>
          ))
        )}
      </div>
    </Card>
  );
}
