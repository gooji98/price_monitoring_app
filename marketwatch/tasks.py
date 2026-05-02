try:
    from celery import shared_task
except ImportError:
    shared_task = None

from .services import collect_market_snapshot


def refresh_market_prices_now():
    return collect_market_snapshot()


if shared_task is not None:
    refresh_market_prices = shared_task(name="marketwatch.tasks.refresh_market_prices")(refresh_market_prices_now)
else:
    refresh_market_prices = refresh_market_prices_now
