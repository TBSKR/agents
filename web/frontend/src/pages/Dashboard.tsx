import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Badge } from '../components/ui';
import {
  PortfolioChart,
  ActiveStrategies,
  ActivityFeed,
  TopOpportunities,
} from '../components/widgets';
import {
  getBotStatus,
  getOpportunities,
  getActivityLog,
  startBot,
  stopBot,
} from '../api/client';
import type { StatusResponse, Opportunity, ActivityLogEntry } from '../types';

export function Dashboard() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [activity, setActivity] = useState<ActivityLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [oppsLoading, setOppsLoading] = useState(false);

  const fetchData = async () => {
    try {
      const [statusData, activityData] = await Promise.all([
        getBotStatus(),
        getActivityLog(20),
      ]);
      setStatus(statusData);
      setActivity(activityData);
    } catch (error) {
      console.error('Failed to fetch status:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchOpportunities = async () => {
    setOppsLoading(true);
    try {
      const opps = await getOpportunities('fullset', { limit: 5 });
      setOpportunities(opps);
    } catch (error) {
      console.error('Failed to fetch opportunities:', error);
    } finally {
      setOppsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    fetchOpportunities();

    // Poll for updates every 10 seconds
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleStartStop = async () => {
    try {
      if (status?.bot_status === 'running' || status?.bot_status === 'scanning') {
        await stopBot();
      } else {
        await startBot('balanced');
      }
      // Refresh status
      fetchData();
    } catch (error) {
      console.error('Failed to toggle bot:', error);
    }
  };

  if (loading || !status) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-text-secondary">Loading...</div>
      </div>
    );
  }

  const isRunning = status.bot_status === 'running' || status.bot_status === 'scanning';

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-border">
        <div className="max-w-7xl mx-auto px-6 py-4 flex justify-between items-center">
          <div className="flex items-center gap-4">
            <h1 className="text-xl font-bold">Kink-Hunter Pro</h1>
            <Badge variant={isRunning ? 'success' : 'default'}>
              {status.mode.toUpperCase()} MODE
            </Badge>
          </div>
          <div className="flex items-center gap-3">
            <Button variant="secondary" onClick={() => navigate('/settings')}>
              Settings
            </Button>
            <Button
              variant={isRunning ? 'secondary' : 'primary'}
              onClick={handleStartStop}
            >
              {isRunning ? 'Stop Bot' : 'Start Bot'}
            </Button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-6 py-6">
        <div className="grid grid-cols-3 gap-6">
          {/* Portfolio Chart - spans 2 columns */}
          <PortfolioChart portfolio={status.portfolio} />

          {/* Active Strategies */}
          <ActiveStrategies
            strategies={status.active_strategies}
            botStatus={status.bot_status}
          />

          {/* Activity Feed */}
          <ActivityFeed entries={activity} />

          {/* Top Opportunities */}
          <TopOpportunities opportunities={opportunities} loading={oppsLoading} />

          {/* Quick Stats */}
          <Card>
            <h3 className="text-lg font-semibold mb-4">Trading Stats</h3>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-text-secondary">Total Trades</span>
                <span className="font-mono">{status.portfolio.total_trades}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Open Positions</span>
                <span className="font-mono">{status.portfolio.num_open_positions}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Realized P&L</span>
                <span
                  className={`font-mono ${
                    status.portfolio.realized_pnl >= 0 ? 'text-profit' : 'text-loss'
                  }`}
                >
                  {status.portfolio.realized_pnl >= 0 ? '+' : ''}$
                  {status.portfolio.realized_pnl.toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Unrealized P&L</span>
                <span
                  className={`font-mono ${
                    status.portfolio.unrealized_pnl >= 0 ? 'text-profit' : 'text-loss'
                  }`}
                >
                  {status.portfolio.unrealized_pnl >= 0 ? '+' : ''}$
                  {status.portfolio.unrealized_pnl.toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Return</span>
                <span
                  className={`font-mono ${
                    status.portfolio.total_return_pct >= 0 ? 'text-profit' : 'text-loss'
                  }`}
                >
                  {status.portfolio.total_return_pct >= 0 ? '+' : ''}
                  {status.portfolio.total_return_pct.toFixed(2)}%
                </span>
              </div>
            </div>
          </Card>
        </div>
      </main>
    </div>
  );
}
