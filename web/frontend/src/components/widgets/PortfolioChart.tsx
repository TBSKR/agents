import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { Card, Stat } from '../ui';
import type { PortfolioSummary } from '../../types';

interface PortfolioChartProps {
  portfolio: PortfolioSummary;
  chartData?: { time: string; value: number }[];
}

export function PortfolioChart({ portfolio, chartData = [] }: PortfolioChartProps) {
  // Generate mock chart data if none provided
  const data = chartData.length > 0 ? chartData : generateMockData(portfolio.total_value);

  const formatCurrency = (value: number) =>
    value.toLocaleString('en-US', { style: 'currency', currency: 'USD' });

  const formatPnl = (value: number) => {
    const sign = value >= 0 ? '+' : '';
    return sign + formatCurrency(value);
  };

  return (
    <Card className="col-span-2">
      <h3 className="text-lg font-semibold mb-4">Portfolio Value</h3>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <defs>
              <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#58A6FF" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#58A6FF" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="time"
              stroke="#8B949E"
              fontSize={12}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              stroke="#8B949E"
              fontSize={12}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => `$${v}`}
              domain={['dataMin - 50', 'dataMax + 50']}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#161B22',
                border: '1px solid #30363D',
                borderRadius: '8px',
              }}
              labelStyle={{ color: '#8B949E' }}
              itemStyle={{ color: '#58A6FF' }}
              formatter={(value) => [formatCurrency(value as number), 'Value']}
            />
            <Area
              type="monotone"
              dataKey="value"
              stroke="#58A6FF"
              strokeWidth={2}
              fill="url(#colorValue)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="grid grid-cols-4 gap-4 mt-4 pt-4 border-t border-border">
        <Stat label="Total Value" value={formatCurrency(portfolio.total_value)} mono />
        <Stat label="Cash" value={formatCurrency(portfolio.cash_balance)} mono />
        <Stat label="Positions" value={formatCurrency(portfolio.positions_value)} mono />
        <Stat
          label="Total P&L"
          value={formatPnl(portfolio.total_pnl)}
          positive={portfolio.total_pnl >= 0}
          negative={portfolio.total_pnl < 0}
          mono
        />
      </div>
    </Card>
  );
}

function generateMockData(currentValue: number) {
  const points = 24;
  const data = [];
  let value = currentValue * 0.95;

  for (let i = 0; i < points; i++) {
    const hour = i.toString().padStart(2, '0') + ':00';
    data.push({ time: hour, value: Math.round(value * 100) / 100 });
    value += (Math.random() - 0.45) * 10;
  }

  // Ensure last point matches current value
  data[data.length - 1].value = currentValue;
  return data;
}
