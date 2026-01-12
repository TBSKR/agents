import { Card } from '../ui';
import type { ActivityLogEntry } from '../../types';

interface ActivityFeedProps {
  entries: ActivityLogEntry[];
}

export function ActivityFeed({ entries }: ActivityFeedProps) {
  const typeColors: Record<string, string> = {
    scan: 'text-accent',
    trade: 'text-profit',
    info: 'text-text-secondary',
    error: 'text-loss',
  };

  const formatTime = (timestamp: string) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  return (
    <Card className="max-h-80 overflow-hidden flex flex-col">
      <h3 className="text-lg font-semibold mb-4">Live Activity</h3>
      <div className="flex-1 overflow-y-auto space-y-2 font-mono text-sm">
        {entries.length === 0 ? (
          <div className="text-text-secondary text-center py-4 font-sans">
            No recent activity
          </div>
        ) : (
          entries.map((e, i) => (
            <div key={i} className="flex gap-2 items-start">
              <span className="text-text-secondary shrink-0">
                {formatTime(e.timestamp)}
              </span>
              <span className={`${typeColors[e.type]} shrink-0`}>
                [{e.type.toUpperCase()}]
              </span>
              <span className="text-text-primary break-words">{e.message}</span>
            </div>
          ))
        )}
      </div>
    </Card>
  );
}
