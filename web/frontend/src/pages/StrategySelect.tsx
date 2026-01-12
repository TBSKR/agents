import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Badge } from '../components/ui';
import { startBot } from '../api/client';
import { STRATEGY_PRESETS, STRATEGY_INFO } from '../types';

export function StrategySelect() {
  const navigate = useNavigate();
  const [selected, setSelected] = useState('balanced');
  const [starting, setStarting] = useState(false);

  const handleStart = async () => {
    setStarting(true);
    try {
      await startBot(selected);
      navigate('/dashboard');
    } catch (error) {
      console.error('Failed to start bot:', error);
      setStarting(false);
    }
  };

  return (
    <div className="min-h-screen bg-background py-12 px-6">
      <div className="max-w-4xl mx-auto">
        <div className="text-center mb-12">
          <h1 className="text-3xl font-bold mb-4">Choose Your Strategy</h1>
          <p className="text-text-secondary">
            Select a preset that matches your risk tolerance. You can customize
            later.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-12">
          {STRATEGY_PRESETS.map((preset) => (
            <Card
              key={preset.id}
              hover
              className={`relative ${
                selected === preset.id
                  ? 'border-accent ring-1 ring-accent'
                  : ''
              }`}
              onClick={() => setSelected(preset.id)}
            >
              {preset.id === 'balanced' && (
                <Badge variant="success" className="absolute -top-2 -right-2">
                  Recommended
                </Badge>
              )}
              <h3 className="text-xl font-semibold mb-2">{preset.name}</h3>
              <p className="text-text-secondary text-sm mb-4">
                {preset.description}
              </p>
              <div className="text-profit font-mono text-2xl mb-4">
                {preset.expectedReturn} APY
              </div>
              <div className="flex flex-wrap gap-2">
                {preset.strategies.map((s) => (
                  <Badge key={s}>{STRATEGY_INFO[s].label}</Badge>
                ))}
              </div>
            </Card>
          ))}
        </div>

        <div className="text-center space-y-4">
          <Button
            size="lg"
            onClick={handleStart}
            disabled={starting}
            className="min-w-[200px]"
          >
            {starting ? 'Starting...' : 'Start Paper Trading'}
          </Button>
          <div>
            <Button
              variant="secondary"
              onClick={() => navigate('/dashboard')}
            >
              Skip Setup
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
