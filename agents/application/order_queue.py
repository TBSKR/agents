"""
Order Queue - Manages pending orders and tracks partial fills.

This module provides:
- Order submission and tracking
- Pending order queue management
- Partial fill handling
- Order cancellation and expiration
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from enum import Enum
import uuid

from agents.application.fill_simulator import (
    FillSimulator, ExecutionResult, MarketConditions, OrderSide, OrderType
)


class OrderStatus(Enum):
    """Status of an order in the queue."""
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REJECTED = "rejected"


@dataclass
class PendingOrder:
    """Represents an order in the queue."""
    order_id: str
    market_id: str
    token_id: str
    side: str  # "BUY" or "SELL"
    order_type: str  # "market" or "limit"
    quantity: float
    limit_price: Optional[float] = None
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    filled_quantity: float = 0.0
    average_fill_price: float = 0.0
    total_cost: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    fills: List[dict] = field(default_factory=list)

    @property
    def remaining_quantity(self) -> float:
        """Quantity still to be filled."""
        return self.quantity - self.filled_quantity

    @property
    def is_complete(self) -> bool:
        """Whether the order is fully filled."""
        return self.remaining_quantity < 0.0001

    @property
    def is_active(self) -> bool:
        """Whether the order can still receive fills."""
        return self.status in [OrderStatus.PENDING, OrderStatus.PARTIAL]

    @property
    def fill_percentage(self) -> float:
        """Percentage of order that has been filled."""
        if self.quantity == 0:
            return 0.0
        return (self.filled_quantity / self.quantity) * 100

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'order_id': self.order_id,
            'market_id': self.market_id,
            'token_id': self.token_id,
            'side': self.side,
            'order_type': self.order_type,
            'quantity': self.quantity,
            'limit_price': self.limit_price,
            'created_at': self.created_at.isoformat(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'filled_quantity': self.filled_quantity,
            'average_fill_price': self.average_fill_price,
            'total_cost': self.total_cost,
            'status': self.status.value,
            'fills': self.fills
        }


@dataclass
class OrderEvent:
    """Event emitted when order state changes."""
    event_type: str  # "submitted", "partial_fill", "filled", "cancelled", "expired"
    order_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    details: dict = field(default_factory=dict)


class OrderQueue:
    """
    Manages a queue of pending orders and tracks their execution.

    Features:
    - Order submission with validation
    - Periodic processing of pending orders
    - Partial fill tracking
    - Order cancellation
    - Expiration handling
    """

    DEFAULT_ORDER_TTL = 3600  # 1 hour default time-to-live

    def __init__(
        self,
        fill_simulator: FillSimulator = None,
        default_ttl_seconds: int = None
    ):
        """
        Initialize the order queue.

        Args:
            fill_simulator: FillSimulator for executing orders
            default_ttl_seconds: Default time-to-live for orders
        """
        self.fill_simulator = fill_simulator or FillSimulator()
        self.default_ttl = default_ttl_seconds or self.DEFAULT_ORDER_TTL
        self.pending_orders: Dict[str, PendingOrder] = {}
        self.completed_orders: Dict[str, PendingOrder] = {}
        self.event_history: List[OrderEvent] = []

    def submit_order(
        self,
        market_id: str,
        token_id: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        limit_price: float = None,
        ttl_seconds: int = None
    ) -> str:
        """
        Submit a new order to the queue.

        Args:
            market_id: Market identifier
            token_id: Token identifier
            side: "BUY" or "SELL"
            quantity: Number of units to trade
            order_type: "market" or "limit"
            limit_price: Limit price (required for limit orders)
            ttl_seconds: Time-to-live in seconds

        Returns:
            Order ID

        Raises:
            ValueError: If order parameters are invalid
        """
        # Validate inputs
        if side.upper() not in ["BUY", "SELL"]:
            raise ValueError(f"Invalid side: {side}")

        if order_type.lower() not in ["market", "limit"]:
            raise ValueError(f"Invalid order type: {order_type}")

        if order_type.lower() == "limit" and limit_price is None:
            raise ValueError("Limit price required for limit orders")

        if quantity <= 0:
            raise ValueError("Quantity must be positive")

        # Create order
        order_id = str(uuid.uuid4())[:8]
        ttl = ttl_seconds or self.default_ttl

        order = PendingOrder(
            order_id=order_id,
            market_id=market_id,
            token_id=token_id,
            side=side.upper(),
            order_type=order_type.lower(),
            quantity=quantity,
            limit_price=limit_price,
            expires_at=datetime.now() + timedelta(seconds=ttl)
        )

        self.pending_orders[order_id] = order

        # Record event
        self._emit_event(OrderEvent(
            event_type="submitted",
            order_id=order_id,
            details={
                'side': side,
                'quantity': quantity,
                'order_type': order_type,
                'limit_price': limit_price
            }
        ))

        return order_id

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a pending order.

        Args:
            order_id: ID of order to cancel

        Returns:
            True if cancelled, False if order not found or not cancellable
        """
        if order_id not in self.pending_orders:
            return False

        order = self.pending_orders[order_id]

        if not order.is_active:
            return False

        order.status = OrderStatus.CANCELLED
        self._move_to_completed(order_id)

        self._emit_event(OrderEvent(
            event_type="cancelled",
            order_id=order_id,
            details={'filled_quantity': order.filled_quantity}
        ))

        return True

    def get_order(self, order_id: str) -> Optional[PendingOrder]:
        """Get order by ID from pending or completed orders."""
        return self.pending_orders.get(order_id) or self.completed_orders.get(order_id)

    def get_pending_orders(self, token_id: str = None) -> List[PendingOrder]:
        """
        Get all pending orders, optionally filtered by token.

        Args:
            token_id: Optional token ID to filter by

        Returns:
            List of pending orders
        """
        orders = list(self.pending_orders.values())

        if token_id:
            orders = [o for o in orders if o.token_id == token_id]

        return orders

    def process_pending_orders(
        self,
        market_conditions: Dict[str, MarketConditions]
    ) -> List[ExecutionResult]:
        """
        Process all pending orders against current market conditions.

        Args:
            market_conditions: Dict mapping token_id to MarketConditions

        Returns:
            List of ExecutionResults for orders that received fills
        """
        results = []
        now = datetime.now()

        # Process each pending order
        for order_id in list(self.pending_orders.keys()):
            order = self.pending_orders[order_id]

            # Check expiration
            if order.expires_at and now > order.expires_at:
                self._expire_order(order_id)
                continue

            # Skip if no market conditions for this token
            if order.token_id not in market_conditions:
                continue

            conditions = market_conditions[order.token_id]

            # Try to fill the order
            result = self._try_fill_order(order, conditions)

            if result and result.total_quantity > 0:
                results.append(result)

        return results

    def _try_fill_order(
        self,
        order: PendingOrder,
        conditions: MarketConditions
    ) -> Optional[ExecutionResult]:
        """
        Attempt to fill an order against current market conditions.

        Args:
            order: Order to fill
            conditions: Current market conditions

        Returns:
            ExecutionResult if fills occurred, None otherwise
        """
        if order.order_type == "market":
            result = self.fill_simulator.simulate_market_order(
                side=order.side,
                quantity=order.remaining_quantity,
                conditions=conditions
            )
        else:  # limit order
            result = self.fill_simulator.simulate_limit_order(
                side=order.side,
                quantity=order.remaining_quantity,
                limit_price=order.limit_price,
                conditions=conditions
            )

        # Process fills
        if result.total_quantity > 0:
            self._apply_fills(order, result)

        return result if result.total_quantity > 0 else None

    def _apply_fills(self, order: PendingOrder, result: ExecutionResult):
        """Apply fills from an execution result to an order."""
        # Update order with fills
        old_filled = order.filled_quantity
        old_cost = order.total_cost

        order.filled_quantity += result.total_quantity
        order.total_cost += result.total_cost

        # Recalculate average fill price
        if order.filled_quantity > 0:
            order.average_fill_price = order.total_cost / order.filled_quantity

        # Record fills
        for fill in result.fills:
            order.fills.append({
                'price': fill.price,
                'quantity': fill.quantity,
                'timestamp': fill.timestamp.isoformat()
            })

        # Update status
        if order.is_complete:
            order.status = OrderStatus.FILLED
            self._move_to_completed(order.order_id)

            self._emit_event(OrderEvent(
                event_type="filled",
                order_id=order.order_id,
                details={
                    'total_quantity': order.filled_quantity,
                    'average_price': order.average_fill_price,
                    'total_cost': order.total_cost
                }
            ))
        else:
            order.status = OrderStatus.PARTIAL

            self._emit_event(OrderEvent(
                event_type="partial_fill",
                order_id=order.order_id,
                details={
                    'filled_quantity': result.total_quantity,
                    'fill_price': result.average_price,
                    'remaining': order.remaining_quantity
                }
            ))

    def _expire_order(self, order_id: str):
        """Mark an order as expired and move to completed."""
        if order_id not in self.pending_orders:
            return

        order = self.pending_orders[order_id]
        order.status = OrderStatus.EXPIRED
        self._move_to_completed(order_id)

        self._emit_event(OrderEvent(
            event_type="expired",
            order_id=order_id,
            details={'filled_quantity': order.filled_quantity}
        ))

    def _move_to_completed(self, order_id: str):
        """Move an order from pending to completed."""
        if order_id in self.pending_orders:
            order = self.pending_orders.pop(order_id)
            self.completed_orders[order_id] = order

    def _emit_event(self, event: OrderEvent):
        """Record an order event."""
        self.event_history.append(event)

    def get_queue_stats(self) -> dict:
        """Get statistics about the order queue."""
        pending = list(self.pending_orders.values())
        completed = list(self.completed_orders.values())

        return {
            'pending_count': len(pending),
            'pending_value': sum(o.quantity * (o.limit_price or 0.5) for o in pending),
            'completed_count': len(completed),
            'filled_count': len([o for o in completed if o.status == OrderStatus.FILLED]),
            'cancelled_count': len([o for o in completed if o.status == OrderStatus.CANCELLED]),
            'expired_count': len([o for o in completed if o.status == OrderStatus.EXPIRED]),
            'partial_fills': len([o for o in pending if o.status == OrderStatus.PARTIAL])
        }

    def clear_completed(self, older_than_hours: int = 24):
        """
        Clear old completed orders to free memory.

        Args:
            older_than_hours: Remove orders completed more than this many hours ago
        """
        cutoff = datetime.now() - timedelta(hours=older_than_hours)

        to_remove = [
            order_id for order_id, order in self.completed_orders.items()
            if order.created_at < cutoff
        ]

        for order_id in to_remove:
            del self.completed_orders[order_id]
