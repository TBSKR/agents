import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Slider, Toggle } from '../components/ui';
import { getSettings, updateSettings } from '../api/client';
import { STRATEGY_INFO } from '../types';
import type { StrategyType } from '../types';

export function Settings() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [settings, setSettings] = useState({
    risk_appetite: 0.5,
    strategies_enabled: {
      fullset: true,
      endgame: true,
      oracle: false,
      rewards: true,
    } as Record<StrategyType, boolean>,
    max_capital: 1000,
  });

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      const data = await getSettings();
      setSettings({
        risk_appetite: data.risk_appetite,
        strategies_enabled: data.strategies_enabled as Record<StrategyType, boolean>,
        max_capital: data.max_capital,
      });
    } catch (error) {
      console.error('Failed to load settings:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateSettings(settings);
      navigate('/dashboard');
    } catch (error) {
      console.error('Failed to save settings:', error);
    } finally {
      setSaving(false);
    }
  };

  const getRiskLabel = (value: number) => {
    if (value < 0.33) return 'Conservative';
    if (value < 0.66) return 'Balanced';
    return 'Aggressive';
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-text-secondary">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-border">
        <div className="max-w-2xl mx-auto px-6 py-4 flex justify-between items-center">
          <h1 className="text-xl font-bold">Settings</h1>
          <Button variant="secondary" onClick={() => navigate('/dashboard')}>
            Back to Dashboard
          </Button>
        </div>
      </header>

      {/* Content */}
      <main className="max-w-2xl mx-auto px-6 py-8 space-y-8">
        {/* Risk Appetite */}
        <Card>
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-xl font-semibold">Risk Appetite</h2>
            <span className="text-accent font-medium">
              {getRiskLabel(settings.risk_appetite)}
            </span>
          </div>
          <Slider
            value={settings.risk_appetite * 100}
            onChange={(v) =>
              setSettings((s) => ({ ...s, risk_appetite: v / 100 }))
            }
            min={0}
            max={100}
            labels={['Conservative', 'Balanced', 'Aggressive']}
          />
          <p className="text-text-secondary text-sm mt-4">
            Higher risk means smaller minimum edge requirements, longer time
            horizons, and larger position sizes.
          </p>
        </Card>

        {/* Strategies */}
        <Card>
          <h2 className="text-xl font-semibold mb-6">Strategies</h2>
          <div className="space-y-4">
            {(Object.keys(STRATEGY_INFO) as StrategyType[]).map((key) => (
              <Toggle
                key={key}
                label={STRATEGY_INFO[key].label}
                description={STRATEGY_INFO[key].description}
                checked={settings.strategies_enabled[key]}
                onChange={(checked) =>
                  setSettings((s) => ({
                    ...s,
                    strategies_enabled: {
                      ...s.strategies_enabled,
                      [key]: checked,
                    },
                  }))
                }
              />
            ))}
          </div>
        </Card>

        {/* Max Capital */}
        <Card>
          <h2 className="text-xl font-semibold mb-4">Maximum Capital</h2>
          <div className="flex items-center gap-4">
            <span className="text-2xl font-mono">$</span>
            <input
              type="number"
              value={settings.max_capital}
              onChange={(e) =>
                setSettings((s) => ({
                  ...s,
                  max_capital: parseFloat(e.target.value) || 0,
                }))
              }
              className="flex-1 bg-background border border-border rounded-lg px-4 py-2 text-xl font-mono focus:outline-none focus:border-accent"
            />
          </div>
          <p className="text-text-secondary text-sm mt-4">
            Maximum capital the bot will allocate across all strategies.
          </p>
        </Card>

        {/* Save Button */}
        <div className="flex justify-end gap-4">
          <Button variant="secondary" onClick={() => navigate('/dashboard')}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? 'Saving...' : 'Save Changes'}
          </Button>
        </div>
      </main>
    </div>
  );
}
