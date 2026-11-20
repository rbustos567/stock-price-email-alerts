import json
import os
import smtplib
from email.message import EmailMessage
import yfinance as yf

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def resolve_path(path_value: str) -> str:
    if os.path.isabs(path_value):
        return path_value
    return os.path.join(BASE_DIR, path_value)


CONFIG_FILE = resolve_path(os.environ.get("ALERTS_CONFIG_FILE", "alerts_config.json"))
STATE_FILE = resolve_path(os.environ.get("ALERTS_STATE_FILE", "triggered_alerts.json"))

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
SENDER_EMAIL = os.environ["ALERT_EMAIL_FROM"]
EMAIL_PASSWORD = os.environ["ALERT_EMAIL_PASS"]
RECIPIENT_EMAIL = os.environ["ALERT_EMAIL_TO"]


def load_alerts_config(config_path: str) -> list[dict]:
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    alerts = data.get("alerts")
    if not isinstance(alerts, list):
        raise ValueError(f"Invalid config format in {config_path}: expected 'alerts' list.")

    validated = []
    for item in alerts:
        ticker = str(item["ticker"]).strip().upper()
        condition = str(item["condition"]).strip().lower()
        target = float(item["target"])
        raw_reset = item.get("reset_pct", None)
        reset_pct = float(raw_reset) if raw_reset is not None else None

        if condition not in ("lte", "gte"):
            raise ValueError(
                f"Invalid condition '{condition}' for {ticker}. Use 'lte' or 'gte'."
            )

        if reset_pct is not None and reset_pct < 0:
            raise ValueError(f"Invalid negative reset_pct for {ticker}: {reset_pct}")

        validated.append({
            "ticker": ticker,
            "condition": condition,
            "target": target,
            "reset_pct": reset_pct,
        })

    return validated


def load_state(state_path: str = STATE_FILE) -> set[str]:
    if not os.path.exists(state_path):
        return set()
    with open(state_path, "r", encoding="utf-8") as f:
        return set(json.load(f))


def save_state(triggered: set[str], state_path: str = STATE_FILE) -> None:
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(sorted(triggered), f, indent=2)


def get_price(ticker: str) -> float | None:
    stock = yf.Ticker(ticker)
    price = getattr(stock.fast_info, "last_price", None)
    if price is not None:
        return float(price)

    hist = stock.history(period="1d")
    if not hist.empty:
        return float(hist["Close"].iloc[-1])
    return None


def should_reset(condition: str, target: float, reset_pct: float | None, price: float) -> bool:
    if reset_pct is None or reset_pct <= 0:
        return False

    factor = reset_pct / 100.0
    if condition == "lte":
        reset_level = target * (1.0 + factor)
        return price >= reset_level
    if condition == "gte":
        reset_level = target * (1.0 - factor)
        return price <= reset_level

    return False


def send_email(subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECIPIENT_EMAIL
    msg.set_content(body)

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as smtp:
        smtp.login(SENDER_EMAIL, EMAIL_PASSWORD)
        smtp.send_message(msg)


def main() -> None:
    price_alerts = load_alerts_config(CONFIG_FILE)
    triggered = load_state(STATE_FILE)
    fired_alerts = []
    state_changed = False

    for rule in price_alerts:
        ticker = rule["ticker"]
        condition = rule["condition"]
        target = rule["target"]
        reset_pct = rule["reset_pct"]

        price = get_price(ticker)
        if price is None:
            print(f"[WARN] Could not fetch price for {ticker}")
            continue

        alert_key = f"{ticker}:{condition}:{target}"

        if alert_key in triggered and should_reset(condition, target, reset_pct, price):
            triggered.remove(alert_key)
            state_changed = True
            print(f"[INFO] Reset alert {alert_key} at price ${price:.2f}")

        matches = (condition == "lte" and price <= target) or (
            condition == "gte" and price >= target
        )

        if matches and alert_key not in triggered:
            operator = "<=" if condition == "lte" else ">="
            fired_alerts.append(
                f"- {ticker}: current price ${price:.2f} (target {operator} ${target:.2f})"
            )
            triggered.add(alert_key)
            state_changed = True

    if fired_alerts:
        body = "The following stock price alerts were triggered:\n\n" + "\n".join(
            fired_alerts
        )
        send_email("Stock Price Alert", body)
        print("Alert email sent.")
    else:
        print("No new alerts triggered.")

    if state_changed:
        save_state(triggered, STATE_FILE)


if __name__ == "__main__":
    main()
