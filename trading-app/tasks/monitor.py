"""
Position Monitor Task

Monitoruje otwarte pozycje i sprawdza warunki SL/TP/Trailing Stop.
"""
import logging
from typing import Dict, Optional

from config import config
from core.database import Database
from core.gate_api import GateIOClient

logger = logging.getLogger(__name__)


class PositionMonitor:
    """Monitor pozycji tradingowych"""

    def __init__(self):
        self.db = Database()
        self.gate = GateIOClient()

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Pobierz aktualną cenę"""
        try:
            ticker = self.gate.get_ticker(symbol)
            return float(ticker.get("last", 0))
        except Exception as e:
            logger.error(f"Failed to get price for {symbol}: {e}")
            return None

    def calculate_pnl(self, position: Dict, current_price: float) -> tuple[float, float]:
        """
        Oblicz P&L dla pozycji

        Returns:
            (pnl_amount, pnl_percent)
        """
        entry_price = float(position["entry_price"])
        quantity = float(position["quantity"])
        side = position["side"]

        if side == "long":
            pnl = (current_price - entry_price) * quantity
        else:  # short
            pnl = (entry_price - current_price) * quantity

        pnl_percent = (pnl / (entry_price * quantity)) * 100

        return pnl, pnl_percent

    def check_stop_loss(self, position: Dict, current_price: float) -> bool:
        """Sprawdź czy stop loss został trafiony"""
        stop_loss = position.get("stop_loss")
        if not stop_loss:
            return False

        stop_loss = float(stop_loss)
        side = position["side"]

        if side == "long" and current_price <= stop_loss:
            return True
        elif side == "short" and current_price >= stop_loss:
            return True

        return False

    def check_take_profit(self, position: Dict, current_price: float) -> bool:
        """Sprawdź czy take profit został trafiony"""
        take_profit = position.get("take_profit")
        if not take_profit:
            return False

        take_profit = float(take_profit)
        side = position["side"]

        if side == "long" and current_price >= take_profit:
            return True
        elif side == "short" and current_price <= take_profit:
            return True

        return False

    def update_trailing_stop(self, position: Dict, current_price: float,
                              pnl_percent: float) -> Optional[float]:
        """
        Aktualizuj trailing stop

        Trailing stop aktywuje się po osiągnięciu progu zysku (np. 2%)
        i podąża za ceną w odległości ATR * multiplier
        """
        trailing_distance = position.get("trailing_stop_distance")
        if not trailing_distance:
            return None

        trailing_distance = float(trailing_distance)
        activation_pct = config.risk.trailing_stop_activation if hasattr(config.risk, 'trailing_stop_activation') else 2.0

        # Check if trailing stop should be activated
        if pnl_percent < activation_pct:
            return None

        side = position["side"]
        current_trailing = position.get("trailing_stop_price")

        if side == "long":
            new_trailing = current_price - trailing_distance
            if current_trailing is None or new_trailing > float(current_trailing):
                return new_trailing
        else:  # short
            new_trailing = current_price + trailing_distance
            if current_trailing is None or new_trailing < float(current_trailing):
                return new_trailing

        return None

    def check_trailing_stop_hit(self, position: Dict, current_price: float) -> bool:
        """Sprawdź czy trailing stop został trafiony"""
        trailing_price = position.get("trailing_stop_price")
        if not trailing_price:
            return False

        trailing_price = float(trailing_price)
        side = position["side"]

        if side == "long" and current_price <= trailing_price:
            return True
        elif side == "short" and current_price >= trailing_price:
            return True

        return False

    def close_position(self, position: Dict, current_price: float, reason: str):
        """Zamknij pozycję"""
        position_id = position["id"]
        symbol = position["symbol"]
        is_paper = position.get("is_paper", True)

        logger.info(f"Closing position {position_id} ({symbol}) - {reason}")

        try:
            if is_paper:
                self.db.close_position(position_id, current_price, reason)
            else:
                self.gate.close_position(symbol)
                self.db.close_position(position_id, current_price, reason)

            # Log audit
            self.db.log_event(
                event_type="position_closed",
                category="positions",
                symbol=symbol,
                position_id=position_id,
                details={"reason": reason, "exit_price": current_price},
                triggered_by="monitor"
            )

        except Exception as e:
            logger.error(f"Failed to close position {position_id}: {e}")

    def monitor_position(self, position: Dict):
        """Monitoruj pojedynczą pozycję"""
        symbol = position["symbol"]
        position_id = position["id"]

        # Get current price
        current_price = self.get_current_price(symbol)
        if not current_price:
            return

        # Calculate P&L
        pnl, pnl_percent = self.calculate_pnl(position, current_price)

        # Update P&L in database
        self.db.update_position_pnl(position_id, current_price, pnl, pnl_percent)

        # Check stop loss
        if self.check_stop_loss(position, current_price):
            self.close_position(position, current_price, "stop_loss_hit")
            return

        # Check take profit
        if self.check_take_profit(position, current_price):
            self.close_position(position, current_price, "take_profit_hit")
            return

        # Check trailing stop
        if self.check_trailing_stop_hit(position, current_price):
            self.close_position(position, current_price, "trailing_stop_hit")
            return

        # Update trailing stop if needed
        new_trailing = self.update_trailing_stop(position, current_price, pnl_percent)
        if new_trailing:
            # Update trailing stop in database (would need to add this method)
            logger.debug(f"Updated trailing stop for {symbol}: {new_trailing}")

        logger.debug(f"Position {symbol}: price={current_price}, pnl={pnl:.2f} ({pnl_percent:.2f}%)")

    def run(self):
        """Główna funkcja - monitoruj wszystkie pozycje"""
        positions = self.db.get_open_positions()

        if not positions:
            logger.debug("No open positions to monitor")
            return

        logger.info(f"Monitoring {len(positions)} open positions...")

        for position in positions:
            try:
                self.monitor_position(position)
            except Exception as e:
                logger.error(f"Error monitoring position {position['id']}: {e}")

        logger.info("Position monitoring completed")


def monitor_positions():
    """Task function for scheduler"""
    monitor = PositionMonitor()
    monitor.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    monitor_positions()
