export type BotStatus = 'stopped' | 'running' | 'scanning';

export type StrategyType = 'fullset' | 'endgame' | 'oracle' | 'rewards';

export interface PortfolioSummary {
  total_value: number;
  cash_balance: number;
  positions_value: number;
  total_pnl: number;
  total_return_pct: number;
  realized_pnl: number;
  unrealized_pnl: number;
  num_open_positions: number;
  total_trades: number;
}

export interface Position {
  market_id: string;
  token_id: string;
  question: string;
  outcome: string;
  side: string;
  entry_price: number;
  quantity: number;
  entry_value: number;
  current_price: number;
  current_value: number;
  unrealized_pnl: number;
}

export interface Opportunity {
  id: string;
  name: string;
  strategy: string;
  edge: number;
  edge_pct: number;
  annualized_return?: number;
  liquidity: number;
  days_until_resolution?: number;
  total_cost?: number;
  num_outcomes?: number;
}

export interface ActivityLogEntry {
  timestamp: string;
  type: 'scan' | 'trade' | 'info' | 'error';
  message: string;
}

export interface BotSettings {
  risk_appetite: number;
  strategies_enabled: Record<StrategyType, boolean>;
  max_capital: number;
}

export interface StatusResponse {
  bot_status: BotStatus;
  mode: string;
  portfolio: PortfolioSummary;
  active_strategies: string[];
  uptime_seconds: number;
}

export interface StrategyPreset {
  id: string;
  name: string;
  description: string;
  expectedReturn: string;
  strategies: StrategyType[];
}

export const STRATEGY_PRESETS: StrategyPreset[] = [
  {
    id: 'safe',
    name: 'Safe & Steady',
    description: 'Focus on endgame sweeps and holding rewards',
    expectedReturn: '15-25%',
    strategies: ['endgame', 'rewards'],
  },
  {
    id: 'balanced',
    name: 'Balanced Growth',
    description: 'Mix of all strategies with moderate risk',
    expectedReturn: '25-50%',
    strategies: ['fullset', 'endgame', 'rewards'],
  },
  {
    id: 'aggressive',
    name: 'High Yield',
    description: 'Focus on arbitrage with higher risk tolerance',
    expectedReturn: '50-100%+',
    strategies: ['fullset', 'endgame', 'oracle'],
  },
];

export const STRATEGY_INFO: Record<StrategyType, { label: string; description: string }> = {
  fullset: {
    label: 'Full-Set Arbitrage',
    description: 'Buy all outcomes when total cost is below $1',
  },
  endgame: {
    label: 'Endgame Sweeps',
    description: 'Buy near-certain outcomes close to resolution',
  },
  oracle: {
    label: 'Oracle Timing',
    description: 'Trade on markets about to resolve',
  },
  rewards: {
    label: 'Rewards Farming',
    description: 'Collect USDC rewards from liquidity',
  },
};
