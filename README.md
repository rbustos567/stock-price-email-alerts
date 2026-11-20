# Stock Price Email Alerts

Automated stock price monitoring and email notification script written in Python using `yfinance` and `smtplib`. It reads alert rules from a JSON configuration file, persists triggered alert state to prevent duplicate emails, supports automatic alert re-arming via `reset_pct`, and includes a `cron`-friendly wrapper script with locking and log rotation.

## Features

- **Configurable alert rules (`alerts_config.json`):** Supports `lte` (less than or equal) and `gte` (greater than or equal) target prices per ticker.
- **Duplicate prevention & auto-reset:** Tracks triggered alerts in `triggered_alerts.json` and optionally re-arms an alert when the price moves away from the target by `reset_pct`.
- **Cron-ready wrapper (`run_alerts.sh`):** Loads `.env` automatically, prevents overlapping runs with `flock`, appends logs to `alerts.log`, and clears old logs after a configurable number of days.
- **Lightweight hardware friendly:** Designed to run reliably on low-resource Linux hosts such as a Raspberry Pi Zero W.

## Repository Structure

```text
.
├── env.example
├── alerts_config.json
├── run_alerts.sh
├── stock_alerts.py
└── README.md
```

## Installation
1. Clone the repository:
```bash
   git clone https://github.com/rbustos567/stock-price-email-alerts.git
   cd stock-price-email-alerts
```

2. Install Python dependencies
```bash
   pip install --user --break-system-packages yfinance
```
(On low-RAM boards like Raspberry Pi Zero W, installing heavy system packages such as python3-numpy and python3-pandas via apt first can save compile time.)

3. Configure environment variables:
Copy env.example to .env and fill in your Gmail sender, 16-character App Password, and recipient address:
```bash
   cp env.example .env
   chmod 600 .env
```

4. Make the wrapper script executable:
```bash
   chmod +x run_alerts.sh
```

## Configuration & Usage

1. Edit alerts_config.json:
Define your tickers, conditions ("lte" or "gte"), target prices, and optional reset_pct:

```bash
{
  "alerts": [
    {
      "ticker": "NVDA",
      "condition": "lte",
      "target": 150.0,
      "reset_pct": 5.0
    },
    {
      "ticker": "AMD",
      "condition": "gte",
      "target": 190.0,
      "reset_pct": 5.0
    }
  ]
}
```

2. Run a manual test:
```bash
./run_alerts.sh
cat alerts.log
```

3. Schedule with cron:
Open your crontab with crontab -e and schedule run_alerts.sh (for example, every 30 minutes, Monday through Friday, from 07:00 to 13:00):
```bash
*/30 7-13 * * 1-5 /path/to/stock-price-alerts/run_alerts.sh
```
## Gmail App Password Setup

Gmail requires a **16-character App Password** (rather than your regular account password) when authenticating via `smtplib` with 2-Step Verification enabled:

1. Enable **2-Step Verification** on your Google Account if it is not already active.
2. Go to your Google Account **Security** settings and open **App passwords**.
3. Create a new app password (for example, named `stock-price-alerts`) and copy the generated 16-character code.
4. Paste it into `ALERT_EMAIL_PASS` inside your `.env` file (spaces can be omitted):
   ```env
   ALERT_EMAIL_FROM="your_email@gmail.com"
   ALERT_EMAIL_PASS="xxxxxxxxxxxxxxxx"
   ALERT_EMAIL_TO="recipient@gmail.com"

## Resetting Alerts
- **Automatic:** When reset_pct is set (e.g., 5.0), an lte alert resets once the price rises to target * (1 + reset_pct / 100), and a gte alert resets once the price drops to target * (1 - reset_pct / 100).
- **Manual:** Remove specific entries or delete triggered_alerts.json to re-arm alerts immediately.
