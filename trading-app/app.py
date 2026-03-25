"""
Trading Agent - Streamlit Dashboard

Main entry point for the trading application.
"""
import streamlit as st
from datetime import datetime

from config import config
from core.database import Database
from core.gate_api import GateIOClient
from core.ollama_client import OllamaClient
from core.scheduler import TradingScheduler

# Page config
st.set_page_config(
    page_title="Trading Agent",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
if "scheduler" not in st.session_state:
    st.session_state.scheduler = TradingScheduler()

if "db" not in st.session_state:
    st.session_state.db = Database()

if "gate" not in st.session_state:
    st.session_state.gate = GateIOClient()

if "ollama" not in st.session_state:
    st.session_state.ollama = OllamaClient()


def render_sidebar():
    """Render sidebar with controls"""
    st.sidebar.title("Trading Agent")

    # Status indicators
    st.sidebar.subheader("System Status")

    col1, col2 = st.sidebar.columns(2)

    # Paper trading indicator
    is_paper = config.risk.paper_trading
    col1.metric(
        "Mode",
        "PAPER" if is_paper else "LIVE",
        delta=None,
        help="Paper trading mode is " + ("enabled" if is_paper else "disabled")
    )

    # Trading enabled indicator
    is_enabled = config.risk.trading_enabled
    col2.metric(
        "Trading",
        "ON" if is_enabled else "OFF",
        delta=None
    )

    st.sidebar.divider()

    # Scheduler controls
    st.sidebar.subheader("Scheduler")
    scheduler = st.session_state.scheduler

    col1, col2 = st.sidebar.columns(2)

    if col1.button("▶ Start", use_container_width=True, disabled=scheduler.is_running):
        scheduler.start()
        st.rerun()

    if col2.button("⏹ Stop", use_container_width=True, disabled=not scheduler.is_running):
        scheduler.stop()
        st.rerun()

    # Show job status
    if scheduler.is_running:
        st.sidebar.success("Scheduler running")
        jobs = scheduler.get_jobs_status()
        for job_id, info in jobs.items():
            status_icon = "✅" if info["status"] == "scheduled" else "⏸"
            st.sidebar.text(f"{status_icon} {job_id}")
    else:
        st.sidebar.warning("Scheduler stopped")

    st.sidebar.divider()

    # Connection status
    st.sidebar.subheader("Connections")

    # GATE.io
    gate = st.session_state.gate
    gate_ok = gate.test_connection()
    if gate_ok:
        st.sidebar.success("GATE.io: Connected")
    else:
        st.sidebar.error("GATE.io: Disconnected")

    # Ollama
    ollama = st.session_state.ollama
    ollama_ok = ollama.is_available()
    if ollama_ok:
        st.sidebar.success("Ollama: Available")
    else:
        st.sidebar.warning("Ollama: Unavailable")

    st.sidebar.divider()

    # Quick links
    st.sidebar.subheader("Quick Actions")

    if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
        st.rerun()

    if st.sidebar.button("🚨 Close All Positions", use_container_width=True,
                         type="secondary"):
        st.sidebar.warning("Not implemented yet")


def render_main_dashboard():
    """Render main dashboard content"""
    st.title("📈 Trading Dashboard")

    # Top metrics row
    col1, col2, col3, col4 = st.columns(4)

    db = st.session_state.db
    gate = st.session_state.gate

    # Try to get account info
    try:
        if gate.test_connection():
            balance = gate.get_balance()
            equity = gate.get_equity()
        else:
            balance = 0
            equity = 0
    except Exception:
        balance = 0
        equity = 0

    col1.metric("Balance", f"${balance:,.2f}")
    col2.metric("Equity", f"${equity:,.2f}")

    # Get open positions count
    try:
        positions = db.get_open_positions()
        pos_count = len(positions)
    except Exception:
        positions = []
        pos_count = 0

    col3.metric("Open Positions", pos_count)

    # Daily P&L placeholder
    col4.metric("Today's P&L", "$0.00", delta="0%")

    st.divider()

    # Two columns layout
    left_col, right_col = st.columns([2, 1])

    with left_col:
        st.subheader("Active Positions")

        if positions:
            for pos in positions:
                with st.container(border=True):
                    pcol1, pcol2, pcol3, pcol4 = st.columns([2, 1, 1, 1])

                    pcol1.write(f"**{pos['symbol']}** ({pos['side'].upper()})")
                    pcol2.write(f"Size: {pos['quantity']}")
                    pcol3.write(f"Entry: ${float(pos['entry_price']):,.2f}")

                    pnl = float(pos.get('unrealized_pnl', 0))
                    pnl_pct = float(pos.get('unrealized_pnl_percent', 0))

                    if pnl >= 0:
                        pcol4.success(f"+${pnl:,.2f} ({pnl_pct:+.2f}%)")
                    else:
                        pcol4.error(f"-${abs(pnl):,.2f} ({pnl_pct:+.2f}%)")
        else:
            st.info("No open positions")

    with right_col:
        st.subheader("Recent Signals")

        try:
            signals = db.get_recent_signals(hours=24, limit=5)
        except Exception:
            signals = []

        if signals:
            for sig in signals:
                signal_type = sig.get('signal_type', 'unknown')
                symbol = sig.get('symbol', 'N/A')
                confidence = float(sig.get('confidence', 0)) * 100

                icon = "🟢" if signal_type == "long" else "🔴" if signal_type == "short" else "⚪"

                st.write(f"{icon} **{symbol}** - {signal_type.upper()} ({confidence:.0f}%)")
        else:
            st.info("No recent signals")

    st.divider()

    # Trading statistics
    st.subheader("Trading Statistics")

    try:
        stats = db.get_trading_stats()
    except Exception:
        stats = {}

    if stats:
        stat_cols = st.columns(len(stats) if stats else 1)
        for idx, (symbol, data) in enumerate(stats.items()):
            with stat_cols[idx]:
                st.write(f"**{symbol}**")
                st.write(f"Total trades: {data.get('total_trades', 0)}")
                st.write(f"Win rate: {data.get('win_rate', 0):.1f}%")
                st.write(f"Total P&L: ${float(data.get('total_pnl', 0)):,.2f}")
    else:
        st.info("No trading history yet")


def main():
    """Main application entry point"""
    render_sidebar()
    render_main_dashboard()

    # Footer
    st.divider()
    st.caption(f"Trading Agent v0.1.0 | Last update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
