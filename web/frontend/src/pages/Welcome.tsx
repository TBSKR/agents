import { useNavigate } from 'react-router-dom';
import { Button, Card } from '../components/ui';

export function Welcome() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-6">
      <Card className="max-w-md text-center p-8">
        <div className="text-5xl mb-6">🎯</div>
        <h1 className="text-3xl font-bold mb-4">Unlock Automated Profits</h1>
        <p className="text-text-secondary mb-8 leading-relaxed">
          Kink-Hunter Pro finds and exploits market inefficiencies on Polymarket
          using proven arbitrage strategies. Start paper trading risk-free.
        </p>
        <div className="space-y-4">
          <Button
            size="lg"
            className="w-full"
            onClick={() => navigate('/onboard/strategy')}
          >
            Get Started
          </Button>
          <Button
            variant="secondary"
            className="w-full"
            onClick={() => navigate('/dashboard')}
          >
            Skip to Dashboard
          </Button>
        </div>
        <p className="text-text-secondary text-sm mt-6">
          Paper trading mode • No real money at risk
        </p>
      </Card>
    </div>
  );
}
