import argparse
import json
import logging
import os
import smtplib
from email.message import EmailMessage
import yfinance as yf

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
logger = logging.getLogger("stocks_alert")


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


def setup_logging(debug: bool = False) -> None:
    env_debug = os.environ.get("DEBUG", "").strip().lower() in ("1", "true", "yes")
    is_debug = debug or env_debug
    level = logging.DEBUG if is_debug else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )

    # Keep noisy third-party loggers quiet unless in debug mode
    third_party_level = logging.DEBUG if is_debug else logging.WARNING
    for noisy_name in ("yfinance", "urllib3", "requests"):
        logging.getLogger(noisy_name).setLevel(third_party_level)

    logger.debug("Logging initialized at level %s", logging.getLevelName(level))
    logger.debug("BASE_DIR=%s", BASE_DIR)
    logger.debug("CONFIG_FILE=%s", CONFIG_FILE)
    logger.debug("STATE_FILE=%s", STATE_FILE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor stock prices with yfinance and send email alerts."
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose DEBUG logging (or set DEBUG=1 in environment).",
    )
    return parser.parse_args()


def load_alerts_config(config_path: str) -> list[dict]:
    logger.debug("Loading alerts config from %s", config_path)
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

    logger.info("Loaded %d alert rule(s) from %s", len(validated), config_path)
    logger.debug("Validated rules: %s", validated)
    return validated


def load_state(state_path: str = STATE_FILE) -> set[str]:
    if not os.path.exists(state_path):
        logger.debug("State file %s does not exist; starting with empty state", state_path)
        return set()
    with open(state_path, "r", encoding="utf-8") as f:
        state = set(json.load(f))
    logger.debug("Loaded %d triggered alert(s) from %s: %s", len(state), state_path, sorted(state))
    return state


def save_state(triggered: set[str], state_path: str = STATE_FILE) -> None:
    logger.debug("Saving %d triggered alert(s) to %s", len(triggered), state_path)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(sorted(triggered), f, indent=2)
    logger.info("Updated state file %s (%d active triggered alert(s))", state_path, len(triggered))


def get_price(ticker: str) -> float | None:
    logger.debug("Fetching price for %s", ticker)
    stock = yf.Ticker(ticker)

    try:
        price = getattr(stock.fast_info, "last_price", None)
    except Exception as exc:
        logger.debug("fast_info lookup failed for %s: %s", ticker, exc)
        price = None

    if price is not None:
        val = float(price)
        logger.debug("Got %s price via fast_info.last_price: $%.4f", ticker, val)
        return val

    logger.debug("fast_info.last_price unavailable for %s; falling back to 1d history", ticker)
    hist = stock.history(period="1d")
    if not hist.empty:
        val = float(hist["Close"].iloc[-1])
        logger.debug("Got %s price via 1d history Close: $%.4f", ticker, val)
        return val

    logger.warning("Could not fetch price for %s from fast_info or 1d history", ticker)
    return None


def should_reset(condition: str, target: float, reset_pct: float | None, price: float) -> bool:
    if reset_pct is None or reset_pct <= 0:
        logger.debug("Auto-reset disabled for target=%.2f (reset_pct=%s)", target, reset_pct)
        return False

    factor = reset_pct / 100.0
    if condition == "lte":
        reset_level = target * (1.0 + factor)
        met = price >= reset_level
        logger.debug(
            "Reset check (lte): price=%.4f >= reset_level=%.4f (target=%.2f + %.2f%%) -> %s",
            price,
            reset_level,
            target,
            reset_pct,
            met,
        )
        return met

    if condition == "gte":
        reset_level = target * (1.0 - factor)
        met = price <= reset_level
        logger.debug(
            "Reset check (gte): price=%.4f <= reset_level=%.4f (target=%.2f - %.2f%%) -> %s",
            price,
            reset_level,
            target,
            reset_pct,
            met,
        )
        return met

    return False


def send_email(subject: str, body: str) -> None:
    logger.debug(
        "Preparing email via %s:%s from=%s to=%s subject=%r",
        SMTP_SERVER,
        SMTP_PORT,
        SENDER_EMAIL,
        RECIPIENT_EMAIL,
        subject,
    )
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECIPIENT_EMAIL
    msg.set_content(body)

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as smtp:
        logger.debug("Connected to SMTP SSL server; logging in...")
        smtp.login(SENDER_EMAIL, EMAIL_PASSWORD)
        logger.debug("SMTP login successful; sending message...")
        smtp.send_message(msg)

    logger.info("Alert email sent to %s", RECIPIENT_EMAIL)


def main() -> None:
    args = parse_args()
    setup_logging(debug=args.debug)

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
            continue

        alert_key = f"{ticker}:{condition}:{target}"
        is_triggered = alert_key in triggered
        logger.debug(
            "Evaluating rule %s: price=$%.4f, target=$%.2f, already_triggered=%s",
            alert_key,
            price,
            target,
            is_triggered,
        )

        if is_triggered and should_reset(condition, target, reset_pct, price):
            triggered.remove(alert_key)
            is_triggered = False
            state_changed = True
            logger.info("Reset alert %s at price $%.2f", alert_key, price)

        matches = (condition == "lte" and price <= target) or (
            condition == "gte" and price >= target
        )
        logger.debug("Condition match for %s: %s", alert_key, matches)

        if matches and not is_triggered:
            operator = "<=" if condition == "lte" else ">="
            fired_alerts.append(
                f"- {ticker}: current price ${price:.2f} (target {operator} ${target:.2f})"
            )
            triggered.add(alert_key)
            state_changed = True
            logger.info(
                "Triggered alert %s at price $%.2f (target %s $%.2f)",
                alert_key,
                price,
                operator,
                target,
            )

    if fired_alerts:
        body = "The following stock price alerts were triggered:\n\n" + "\n".join(
            fired_alerts
        )
        send_email("Stock Price Alert", body)
    else:
        logger.info("No new alerts triggered.")

    if state_changed:
        save_state(triggered, STATE_FILE)
    else:
        logger.debug("State unchanged; skipping state file write")


if __name__ == "__main__":
    main()
