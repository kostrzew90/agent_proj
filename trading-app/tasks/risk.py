"""
Risk Management Task

Kontroluje limity ryzyka i automatycznie zamyka pozycje w przypadku przekroczenia.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List

from config import config
from core.database import Database
from core.gate_api import GateIOClient

logger = logging.getLogger(__name__)


class RiskGuardian:
    """Strażnik ryzyka tradingowego"""

    def __init__(self):
        self.db = Database()
        self.gate = GateIOClient()
        self.cfg = config.risk

    def get_daily_pnl(self) -> float:
        """Oblicz dzisiejszy P&L"""
        try:
            today = datetime.now().date()
            history = self.db.get_position_history(limit=100)

            daily_pnl = 0.0
            for pos in history:
                closed_at = pos.get("closed_at")
                if closed_at and closed_at.date() == today:
                    daily_pnl += float(pos.get("realized_pnl", 0))

            # Add unrealized P&L from open positions
            open_positions = self.db.get_open_positions()
            for pos in open_positions:
                daily_pnl += float(pos.get("unrealized_pnl", 0))

            return daily_pnl

        except Exception as e:
            logger.error(f"Failed to calculate daily P&L: {e}")
            return 0.0

    def get_account_balance(self) -> float:
        """Pobierz saldo konta"""
        try:
            if self.db.is_paper_trading():
                # For paper trading, use initial balance from config or default
                return float(self.db.get_config("paper_balance", "10000"))
            else:
                return self.gate.get_equity()
        except Exception as e:
            logger.error(f"Failed to get account balance: {e}")
            return 0.0

    def check_daily_loss_limit(self) -> bool:
        """
        Sprawdź czy dzienny limit strat został przekroczony

        Returns:
            True jeśli limit przekroczony
        """
        daily_pnl = self.get_daily_pnl()
        balance = self.get_account_balance()

        if balance <= 0:
            return False

        daily_loss_pct = (daily_pnl / balance) * 100

        limit = self.cfg.daily_loss_limit_percent

        if daily_loss_pct < -limit:
            logger.warning(f"Daily loss limit exceeded: {daily_loss_pct:.2f}% (limit: -{limit}%)")
            return True

        return False

    def check_max_drawdown(self) -> bool:
        """
        Sprawdź maksymalny drawdown

        Returns:
            True jeśli drawdown przekroczony
        """
        # Get equity high watermark
        # This would need additional tracking in database
        return False

    def check_max_positions(self) -> bool:
        """
        Sprawdź czy przekroczono limit otwartych pozycji

        Returns:
            True jeśli za dużo pozycji
        """
        positions = self.db.get_open_positions()
        max_positions = self.cfg.max_open_positions

        if len(positions) > max_positions:
            logger.warning(f"Too many positions: {len(positions)} (max: {max_positions})")
            return True

        return False

    def check_position_sizes(self) -> List[Dict]:
        """
        Sprawdź czy rozmiary pozycji są w normie

        Returns:
            Lista pozycji z przekroczonym rozmiarem
        """
        positions = self.db.get_open_positions()
        balance = self.get_account_balance()
        max_size_pct = self.cfg.max_position_size_percent

        oversized = []

        for pos in positions:
            entry_value = float(pos["entry_price"]) * float(pos["quantity"])
            position_pct = (entry_value / balance) * 100 if balance > 0 else 0

            if position_pct > max_size_pct:
                oversized.append({
                    "position": pos,
                    "size_pct": position_pct,
                    "max_pct": max_size_pct
                })

        return oversized

    def check_leverage_limits(self) -> List[Dict]:
        """
        Sprawdź czy leverage pozycji jest w normie

        Returns:
            Lista pozycji z przekroczonym leverage
        """
        positions = self.db.get_open_positions()
        max_leverage = self.cfg.max_leverage

        over_leveraged = []

        for pos in positions:
            leverage = pos.get("leverage", 1)
            if leverage > max_leverage:
                over_leveraged.append({
                    "position": pos,
                    "leverage": leverage,
                    "max_leverage": max_leverage
                })

        return over_leveraged

    def emergency_close_all(self, reason: str):
        """Zamknij wszystkie pozycje w trybie awaryjnym"""
        positions = self.db.get_open_positions()

        logger.warning(f"EMERGENCY CLOSE ALL - Reason: {reason}")

        for pos in positions:
            try:
                symbol = pos["symbol"]
                position_id = pos["id"]
                is_paper = pos.get("is_paper", True)

                # Get current price
                ticker = self.gate.get_ticker(symbol)
                current_price = float(ticker.get("last", pos["entry_price"]))

                if is_paper:
                    self.db.close_position(position_id, current_price, f"EMERGENCY: {reason}")
                else:
                    self.gate.close_position(symbol)
                    self.db.close_position(position_id, current_price, f"EMERGENCY: {reason}")

                logger.warning(f"Emergency closed {symbol} at {current_price}")

            except Exception as e:
                logger.error(f"Failed to emergency close {pos['symbol']}: {e}")

        # Log audit
        self.db.log_event(
            event_type="emergency_close_all",
            category="risk",
            details={"reason": reason, "positions_closed": len(positions)},
            triggered_by="risk_guardian"
        )

    def disable_trading(self, reason: str):
        """Wyłącz trading"""
        logger.warning(f"Disabling trading: {reason}")
        self.db.set_config("trading_enabled", "false", f"Disabled by risk guardian: {reason}")

        self.db.log_event(
            event_type="trading_disabled",
            category="risk",
            details={"reason": reason},
            triggered_by="risk_guardian"
        )

    def run(self):
        """Główna funkcja - sprawdź wszystkie limity ryzyka"""
        logger.info("Running risk checks...")

        alerts = []

        # Check daily loss limit
        if self.check_daily_loss_limit():
            alerts.append("Daily loss limit exceeded")
            self.disable_trading("Daily loss limit exceeded")
            self.emergency_close_all("Daily loss limit exceeded")
            return

        # Check max positions
        if self.check_max_positions():
            alerts.append("Max positions exceeded")

        # Check position sizes
        oversized = self.check_position_sizes()
        if oversized:
            for item in oversized:
                alerts.append(f"Position {item['position']['symbol']} too large: {item['size_pct']:.1f}%")

        # Check leverage
        over_leveraged = self.check_leverage_limits()
        if over_leveraged:
            for item in over_leveraged:
                alerts.append(f"Position {item['position']['symbol']} over-leveraged: {item['leverage']}x")

        # Log results
        if alerts:
            logger.warning(f"Risk alerts: {alerts}")
            self.db.log_event(
                event_type="risk_alerts",
                category="risk",
                details={"alerts": alerts},
                triggered_by="risk_guardian"
            )
        else:
            logger.info("All risk checks passed")


def check_risk_limits():
    """Task function for scheduler"""
    guardian = RiskGuardian()
    guardian.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    check_risk_limits()
