"""
Holding Rewards Tracker for Polymarket Paper Trading

Track 4% APY holding rewards on eligible positions (political/election markets).
Calculate daily/monthly rewards and find reward-eligible markets.

Eligibility criteria:
- Political markets (e.g., 2028 election predictions)
- Markets with clobRewards configured
- Active/not resolved markets
"""

import json
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from dataclasses import dataclass
from datetime import datetime
import httpx

from agents.polymarket.gamma import GammaMarketClient

if TYPE_CHECKING:
    from agents.application.paper_portfolio import PaperPortfolio


# Keywords indicating reward-eligible markets
ELIGIBLE_KEYWORDS = [
    "2028", "2032", "2036",
    "president", "presidential",
    "congress", "senate", "house",
    "election", "nominee", "nomination",
    "governor", "cabinet", "secretary"
]

# Default APY for holding rewards
DEFAULT_REWARD_APY = 4.0  # 4% annual


@dataclass
class RewardEligiblePosition:
    """A position eligible for holding rewards."""
    market_id: str
    token_id: str
    question: str
    outcome: str
    quantity: float
    entry_price: float
    entry_value: float
    entry_time: datetime
    is_reward_eligible: bool
    reward_rate_apy: float           # e.g., 4.0 for 4%
    estimated_daily_reward: float
    total_rewards_earned: float      # Accumulated rewards based on hold time

    def to_dict(self) -> dict:
        return {
            'market_id': self.market_id,
            'token_id': self.token_id,
            'question': self.question,
            'outcome': self.outcome,
            'quantity': self.quantity,
            'entry_price': self.entry_price,
            'entry_value': self.entry_value,
            'entry_time': self.entry_time.isoformat() if isinstance(self.entry_time, datetime) else self.entry_time,
            'is_reward_eligible': self.is_reward_eligible,
            'reward_rate_apy': self.reward_rate_apy,
            'estimated_daily_reward': self.estimated_daily_reward,
            'total_rewards_earned': self.total_rewards_earned
        }


@dataclass
class RewardsSummary:
    """Summary of all rewards across positions."""
    total_eligible_positions: int
    total_eligible_value: float
    estimated_daily_rewards: float
    estimated_monthly_rewards: float
    estimated_annual_rewards: float
    total_rewards_earned: float
    eligible_markets: List[str]      # Market IDs

    def to_dict(self) -> dict:
        return {
            'total_eligible_positions': self.total_eligible_positions,
            'total_eligible_value': self.total_eligible_value,
            'estimated_daily_rewards': self.estimated_daily_rewards,
            'estimated_monthly_rewards': self.estimated_monthly_rewards,
            'estimated_annual_rewards': self.estimated_annual_rewards,
            'total_rewards_earned': self.total_rewards_earned,
            'eligible_markets': self.eligible_markets
        }


@dataclass
class RewardEligibleMarket:
    """A market that is eligible for holding rewards."""
    market_id: str
    question: str
    liquidity: float
    volume: float
    reward_apy: float
    tags: List[str]
    end_date: str

    def to_dict(self) -> dict:
        return {
            'market_id': self.market_id,
            'question': self.question,
            'liquidity': self.liquidity,
            'volume': self.volume,
            'reward_apy': self.reward_apy,
            'tags': self.tags,
            'end_date': self.end_date
        }


class HoldingRewardsTracker:
    """
    Track 4% APY holding rewards on eligible positions.

    Eligibility is determined by:
    1. Market keywords (political/election related)
    2. clobRewards field from API
    3. Market must be active/not resolved
    """

    def __init__(self, portfolio: "PaperPortfolio"):
        self.portfolio = portfolio
        self.gamma = GammaMarketClient()
        self.reward_apy = DEFAULT_REWARD_APY
        self._market_cache: Dict[str, Dict] = {}  # Cache market data

    def _get_market(self, market_id: str) -> Optional[Dict]:
        """Get market data with caching."""
        if market_id in self._market_cache:
            return self._market_cache[market_id]

        try:
            market = self.gamma.get_market(market_id)
            if market:
                self._market_cache[market_id] = market
            return market
        except Exception:
            return None

    def _is_reward_eligible_by_keywords(self, market: Dict) -> bool:
        """Check if market is eligible based on keywords."""
        question = market.get('question', '').lower()
        description = market.get('description', '').lower()
        combined = f"{question} {description}"

        return any(kw in combined for kw in ELIGIBLE_KEYWORDS)

    def _is_reward_eligible_by_api(self, market: Dict) -> bool:
        """Check if market has clobRewards configured in API."""
        clob_rewards = market.get('clobRewards', [])
        if not clob_rewards:
            return False

        if isinstance(clob_rewards, str):
            try:
                clob_rewards = json.loads(clob_rewards)
            except json.JSONDecodeError:
                return False

        # Check if any rewards are configured
        return len(clob_rewards) > 0

    def _get_reward_rate(self, market: Dict) -> float:
        """Get the reward rate for a market."""
        clob_rewards = market.get('clobRewards', [])
        if not clob_rewards:
            return self.reward_apy

        if isinstance(clob_rewards, str):
            try:
                clob_rewards = json.loads(clob_rewards)
            except json.JSONDecodeError:
                return self.reward_apy

        # If API specifies a rate, use it; otherwise use default
        for reward in clob_rewards:
            if isinstance(reward, dict):
                rate = reward.get('rewardsDailyRate', 0)
                if rate > 0:
                    # Convert daily rate to APY
                    return rate * 365 / 100

        return self.reward_apy

    def is_reward_eligible(self, market: Dict) -> bool:
        """
        Check if a market is eligible for holding rewards.

        Eligible if:
        1. Has clobRewards configured in API, OR
        2. Contains political/election keywords
        """
        # Check if market is active
        if market.get('closed') is True or market.get('archived') is True:
            return False

        # Check API rewards first (most reliable)
        if self._is_reward_eligible_by_api(market):
            return True

        # Fallback to keyword matching
        return self._is_reward_eligible_by_keywords(market)

    def _parse_entry_time(self, entry_time_str: str) -> datetime:
        """Parse entry time string to datetime."""
        try:
            # Handle ISO format
            if 'T' in entry_time_str:
                return datetime.fromisoformat(entry_time_str.replace('Z', '+00:00'))
            # Handle other formats
            return datetime.strptime(entry_time_str, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return datetime.now()

    def get_eligible_positions(self) -> List[RewardEligiblePosition]:
        """Get all positions eligible for rewards."""
        eligible = []

        for token_id, position in self.portfolio.positions.items():
            market = self._get_market(position.market_id)
            if not market:
                continue

            if self.is_reward_eligible(market):
                # Calculate rewards
                reward_rate = self._get_reward_rate(market)
                daily_rate = reward_rate / 365 / 100
                daily_reward = position.entry_value * daily_rate

                # Calculate accumulated rewards
                entry_time = self._parse_entry_time(position.entry_time)
                hold_days = (datetime.now() - entry_time).days
                total_earned = daily_reward * max(hold_days, 0)

                eligible.append(RewardEligiblePosition(
                    market_id=position.market_id,
                    token_id=token_id,
                    question=position.question,
                    outcome=position.outcome,
                    quantity=position.quantity,
                    entry_price=position.entry_price,
                    entry_value=position.entry_value,
                    entry_time=entry_time,
                    is_reward_eligible=True,
                    reward_rate_apy=reward_rate,
                    estimated_daily_reward=daily_reward,
                    total_rewards_earned=total_earned
                ))

        return eligible

    def get_rewards_summary(self) -> RewardsSummary:
        """Get summary of all rewards across positions."""
        eligible = self.get_eligible_positions()

        total_value = sum(p.entry_value for p in eligible)
        daily = sum(p.estimated_daily_reward for p in eligible)
        total_earned = sum(p.total_rewards_earned for p in eligible)

        return RewardsSummary(
            total_eligible_positions=len(eligible),
            total_eligible_value=total_value,
            estimated_daily_rewards=daily,
            estimated_monthly_rewards=daily * 30,
            estimated_annual_rewards=daily * 365,
            total_rewards_earned=total_earned,
            eligible_markets=[p.market_id for p in eligible]
        )

    def find_reward_eligible_markets(
        self,
        min_liquidity: float = 1000,
        limit: int = 20
    ) -> List[RewardEligibleMarket]:
        """Find markets that are eligible for holding rewards."""
        eligible_markets = []

        try:
            # Fetch events (contains tags and markets)
            params = {
                "active": "true",
                "closed": "false",
                "limit": 100
            }
            response = httpx.get(self.gamma.gamma_events_endpoint, params=params)
            if response.status_code != 200:
                return eligible_markets

            events = response.json()

            for event in events:
                # Extract tags
                tags = event.get('tags', [])
                tag_labels = []
                if isinstance(tags, list):
                    for t in tags:
                        if isinstance(t, dict):
                            label = t.get('label', '')
                            if label:
                                tag_labels.append(label)
                        elif isinstance(t, str):
                            tag_labels.append(t)

                markets = event.get('markets', [])

                for market in markets:
                    # Skip inactive or low liquidity
                    liquidity = float(market.get('liquidity', 0) or 0)
                    if liquidity < min_liquidity:
                        continue

                    if market.get('closed') is True or market.get('archived') is True:
                        continue

                    # Check eligibility
                    if self.is_reward_eligible(market):
                        reward_rate = self._get_reward_rate(market)

                        eligible_markets.append(RewardEligibleMarket(
                            market_id=str(market.get('id', '')),
                            question=market.get('question', ''),
                            liquidity=liquidity,
                            volume=float(market.get('volume', 0) or 0),
                            reward_apy=reward_rate,
                            tags=tag_labels,
                            end_date=market.get('endDate', '')
                        ))

        except Exception as e:
            print(f"Error fetching markets: {e}")

        # Sort by liquidity (highest first)
        eligible_markets = sorted(eligible_markets, key=lambda x: -x.liquidity)

        return eligible_markets[:limit]

    def calculate_projected_rewards(
        self,
        investment_amount: float,
        hold_days: int = 365
    ) -> Dict[str, Any]:
        """
        Calculate projected rewards for a hypothetical investment.

        Args:
            investment_amount: Amount to invest
            hold_days: Number of days to hold

        Returns:
            Projected rewards breakdown
        """
        daily_rate = self.reward_apy / 365 / 100
        daily_reward = investment_amount * daily_rate
        total_reward = daily_reward * hold_days

        return {
            'investment': investment_amount,
            'hold_days': hold_days,
            'apy': self.reward_apy,
            'daily_reward': daily_reward,
            'weekly_reward': daily_reward * 7,
            'monthly_reward': daily_reward * 30,
            'annual_reward': daily_reward * 365,
            'total_projected_reward': total_reward,
            'effective_return_pct': (total_reward / investment_amount) * 100
        }


def print_rewards_summary(tracker: HoldingRewardsTracker):
    """Pretty print rewards summary."""
    summary = tracker.get_rewards_summary()

    print("\n" + "="*50)
    print("  HOLDING REWARDS SUMMARY")
    print("="*50)
    print(f"  Eligible Positions:     {summary.total_eligible_positions}")
    print(f"  Eligible Value:         ${summary.total_eligible_value:,.2f}")
    print(f"  Daily Rewards:          ${summary.estimated_daily_rewards:.4f}")
    print(f"  Monthly Rewards:        ${summary.estimated_monthly_rewards:.2f}")
    print(f"  Annual Rewards (est):   ${summary.estimated_annual_rewards:.2f}")
    print(f"  Total Earned:           ${summary.total_rewards_earned:.2f}")
    print("="*50)


def print_eligible_markets(markets: List[RewardEligibleMarket]):
    """Pretty print reward-eligible markets."""
    if not markets:
        print("No reward-eligible markets found.")
        return

    print("\n" + "="*70)
    print("  REWARD-ELIGIBLE MARKETS")
    print("  Markets where you can earn holding rewards (4% APY)")
    print("="*70)

    for i, m in enumerate(markets[:15], 1):
        print(f"\n{i}. {m.question[:55]}{'...' if len(m.question) > 55 else ''}")
        print(f"   APY: {m.reward_apy:.1f}%")
        print(f"   Liquidity: ${m.liquidity:,.0f}")
        if m.tags:
            print(f"   Tags: {', '.join(m.tags[:3])}")
        if m.end_date:
            print(f"   Ends: {m.end_date[:10]}")

    print("\n" + "="*70)


def print_eligible_positions(positions: List[RewardEligiblePosition]):
    """Pretty print reward-eligible positions."""
    if not positions:
        print("No reward-eligible positions found.")
        return

    print("\n" + "="*70)
    print("  POSITIONS EARNING REWARDS")
    print("="*70)

    for i, pos in enumerate(positions, 1):
        print(f"\n{i}. {pos.question[:50]}{'...' if len(pos.question) > 50 else ''}")
        print(f"   Outcome: {pos.outcome}")
        print(f"   Value: ${pos.entry_value:.2f}")
        print(f"   APY: {pos.reward_rate_apy:.1f}%")
        print(f"   Daily Reward: ${pos.estimated_daily_reward:.4f}")
        print(f"   Total Earned: ${pos.total_rewards_earned:.2f}")

    print("\n" + "="*70)


if __name__ == "__main__":
    # Test finding eligible markets
    from agents.application.paper_portfolio import PaperPortfolio

    portfolio = PaperPortfolio(initial_balance=1000)
    tracker = HoldingRewardsTracker(portfolio)

    print("Finding reward-eligible markets...")
    markets = tracker.find_reward_eligible_markets(min_liquidity=100)
    print_eligible_markets(markets)

    # Show projected rewards
    print("\n" + "="*50)
    print("  PROJECTED REWARDS CALCULATOR")
    print("="*50)
    projection = tracker.calculate_projected_rewards(1000, hold_days=365)
    print(f"  Investment: ${projection['investment']:,.2f}")
    print(f"  Hold Period: {projection['hold_days']} days")
    print(f"  APY: {projection['apy']:.1f}%")
    print(f"  Daily Reward: ${projection['daily_reward']:.4f}")
    print(f"  Monthly Reward: ${projection['monthly_reward']:.2f}")
    print(f"  Annual Reward: ${projection['annual_reward']:.2f}")
    print("="*50)
