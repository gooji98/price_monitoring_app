# Price Monitoring

## Setup

```powershell
python -m pip install -r requirements.txt
python manage.py migrate
```

PostgreSQL is configured through `.env`:

```env
DB_NAME=price_monitoring_board
DB_USER=postgres
DB_PASSWORD=....
DB_HOST=localhost
DB_PORT=5432
```

## Run

Open three terminals from the project directory:

```powershell
python manage.py runserver 127.0.0.1:8000
```

```powershell
python -m celery -A price_monitor worker -P solo -l info
```

```powershell
python -m celery -A price_monitor beat -l info
```

Celery Beat queues `marketwatch.tasks.refresh_market_prices` every 60 seconds.
The dashboard reads the latest stored quotes from PostgreSQL.

## Alerts

Open `/admin/`, edit `Monitor settings`, and enable Telegram alerts.
Every configured Telegram interval, the bot sends cards that are in `warning` or `danger`.

Fill `Telegram bot token`. Users can send `/start` to the bot to subscribe and `/stop` to unsubscribe.
`Telegram chat id` is still supported as a fixed fallback recipient.

## Wallboard

Use the `Full` button on the dashboard to enter wallboard fullscreen mode.
Filters are hidden in fullscreen and the card grid becomes more compact.
