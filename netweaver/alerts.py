#!/usr/bin/env python3
"""NetWeaver Alert System — Send alerts to Telegram/Slack via webhooks."""

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any

TINI = Path.home() / "Documents/myhermes/.tini"
ALERTS_STATE = TINI / "alerts_state.json"

# Try to import requests
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def load_state() -> Dict[str, Any]:
    """Load alert state (last sent timestamps)."""
    if not ALERTS_STATE.exists():
        return {"last_sent": {}, "suppressed": {}}
    
    try:
        return json.loads(ALERTS_STATE.read_text())
    except (json.JSONDecodeError, OSError):
        return {"last_sent": {}, "suppressed": {}}


def save_state(state: Dict[str, Any]) -> None:
    """Save alert state."""
    try:
        ALERTS_STATE.write_text(json.dumps(state, indent=2, default=str))
    except OSError:
        pass


def should_send(alert_type: str, state: Dict[str, Any], cooldown: int = 300) -> bool:
    """Check if alert should be sent (respects cooldown)."""
    last_sent = state.get("last_sent", {}).get(alert_type, 0)
    return (time.time() - last_sent) >= cooldown


def mark_sent(alert_type: str, state: Dict[str, Any]) -> None:
    """Mark alert as sent."""
    if "last_sent" not in state:
        state["last_sent"] = {}
    state["last_sent"][alert_type] = time.time()


def send_telegram(message: str, bot_token: str, chat_id: str) -> bool:
    """Send alert via Telegram Bot API."""
    if not HAS_REQUESTS:
        print("ERROR: requests library not installed", file=sys.stderr)
        return False
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except requests.RequestException as e:
        print(f"Telegram send failed: {e}", file=sys.stderr)
        return False


def send_slack(message: str, webhook_url: str) -> bool:
    """Send alert via Slack webhook."""
    if not HAS_REQUESTS:
        print("ERROR: requests library not installed", file=sys.stderr)
        return False
    
    payload = {"text": message}
    
    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        return resp.status_code == 200
    except requests.RequestException as e:
        print(f"Slack send failed: {e}", file=sys.stderr)
        return False


def send_alert(
    alert_type: str,
    title: str,
    message: str,
    severity: str = "info",
    cooldown: int = 300,
) -> bool:
    """Send alert to configured channels.
    
    Args:
        alert_type: Unique identifier for this alert type (used for cooldown)
        title: Alert title
        message: Alert message body
        severity: "info", "warning", "critical"
        cooldown: Seconds to wait before sending same alert again
    
    Returns:
        True if alert was sent, False if suppressed or failed
    """
    state = load_state()
    
    if not should_send(alert_type, state, cooldown):
        return False
    
    # Format message
    emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(severity, "📢")
    formatted = f"{emoji} *{title}*\n\n{message}"
    
    sent = False
    
    # Check for Telegram config
    telegram_token = os.environ.get("NETWEAVER_TELEGRAM_TOKEN")
    telegram_chat = os.environ.get("NETWEAVER_TELEGRAM_CHAT")
    if telegram_token and telegram_chat:
        if send_telegram(formatted, telegram_token, telegram_chat):
            sent = True
    
    # Check for Slack config
    slack_webhook = os.environ.get("NETWEAVER_SLACK_WEBHOOK")
    if slack_webhook:
        if send_slack(formatted, slack_webhook):
            sent = True
    
    # If no channels configured, just log
    if not sent:
        print(f"[ALERT] {severity.upper()}: {title} — {message}", file=sys.stderr)
    
    mark_sent(alert_type, state)
    save_state(state)
    
    return sent


def alert_daemon_dead(age_seconds: float) -> bool:
    """Alert: daemon heartbeat stale."""
    return send_alert(
        "daemon_dead",
        "Daemon Dead",
        f"Heartbeat stale ({age_seconds:.0f}s old). Watchdog should restart it.",
        severity="critical",
        cooldown=600,
    )


def alert_circuit_breaker_tripped(agents: list) -> bool:
    """Alert: circuit breaker tripped."""
    return send_alert(
        "circuit_breaker",
        "Circuit Breaker Tripped",
        f"Agents paused: {', '.join(agents)}",
        severity="critical",
        cooldown=1800,
    )


def alert_tests_failing(count: int) -> bool:
    """Alert: tests failing."""
    return send_alert(
        "tests_failing",
        "Tests Failing",
        f"{count} tests failing. Check daemon logs.",
        severity="warning",
        cooldown=3600,
    )


def alert_stuck_task(task_id: str, failures: int) -> bool:
    """Alert: task stuck in failure loop."""
    return send_alert(
        f"stuck_{task_id}",
        "Task Stuck",
        f"{task_id} failed {failures} times. Consider quarantine.",
        severity="warning",
        cooldown=7200,
    )


def alert_plan_rejected(plan_id: str, reason: str) -> bool:
    """Alert: plan rejected by reviewer."""
    return send_alert(
        f"rejected_{plan_id}",
        "Plan Rejected",
        f"{plan_id} rejected: {reason}",
        severity="info",
        cooldown=3600,
    )


def main():
    """CLI interface for sending test alerts."""
    if len(sys.argv) < 2:
        print("Usage: alerts.py <test|status>")
        print("  test   — Send a test alert")
        print("  status — Show alert state")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "test":
        print("Sending test alert...")
        sent = send_alert(
            "test_alert",
            "Test Alert",
            "This is a test alert from NetWeaver.",
            severity="info",
            cooldown=0,
        )
        if sent:
            print("✓ Alert sent")
        else:
            print("✗ Alert not sent (no channels configured)")
            print("\nTo configure:")
            print("  Telegram: export NETWEAVER_TELEGRAM_TOKEN=xxx NETWEAVER_TELEGRAM_CHAT=xxx")
            print("  Slack:    export NETWEAVER_SLACK_WEBHOOK=https://hooks.slack.com/...")
    
    elif cmd == "status":
        state = load_state()
        print("Alert State:")
        print(f"  Last sent: {len(state.get('last_sent', {}))} alerts")
        for alert_type, ts in state.get("last_sent", {}).items():
            age = time.time() - ts
            print(f"    {alert_type}: {age:.0f}s ago")


if __name__ == "__main__":
    main()
