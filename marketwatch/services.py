from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone as datetime_timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from time import perf_counter, sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import gzip
import json
import os
import time

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import OperationalError, ProgrammingError
from django.db import transaction
from django.utils import timezone

from .models import GapSample, MarketQuote, MonitorCard, MonitorSettings


BINANCE_URLS = [
    "https://api.binance.com/api/v3/trades?symbol={symbol}&limit=1",
    "https://api1.binance.com/api/v3/trades?symbol={symbol}&limit=1",
    "https://api2.binance.com/api/v3/trades?symbol={symbol}&limit=1",
    "https://api3.binance.com/api/v3/trades?symbol={symbol}&limit=1",
    "https://data-api.binance.vision/api/v3/trades?symbol={symbol}&limit=1",
]
WALLEX_URL = "https://api.wallex.ir/v1/trades?symbol={symbol}"
NOBITEX_URL = "https://apiv2.nobitex.ir/v2/trades/{symbol}"
HISTORY_WINDOW_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class TradePrice:
    price: Decimal
    timestamp: str | None
    latency_ms: int


def build_snapshot():
    cards = _configured_cards(visible_only=True)
    quote_keys = [_quote_key(card) for card in cards]
    quotes = MarketQuote.objects.filter(symbol__in=quote_keys)
    quote_by_symbol = {quote.symbol: quote for quote in quotes}
    rows = [_quote_to_row(card, quote_by_symbol.get(_quote_key(card))) for card in cards]
    fetched_at = max((quote.fetched_at for quote in quotes), default=timezone.now())
    monitor_settings = _monitor_settings()

    return {
        "pollIntervalSeconds": 10,
        "syncIntervalSeconds": monitor_settings.sync_interval_minutes * 60,
        "fetchedAt": timezone.localtime(fetched_at).isoformat(),
        "rows": rows,
    }


def collect_market_snapshot():
    monitor_settings = _monitor_settings()
    if not _sync_is_due(monitor_settings):
        return build_snapshot()

    cards = _configured_cards(visible_only=True)
    symbols = [card.symbol for card in cards]
    timeout = settings.PRICE_MONITOR["REQUEST_TIMEOUT_SECONDS"]
    fetched_at = timezone.now()
    jobs = {}

    for card in cards:
        symbol = card.symbol
        source_exchange = _source_exchange(card).lower()
        compare_exchange = _compare_exchange(card).lower()
        _add_exchange_job(jobs, source_exchange, symbol)
        _add_exchange_job(jobs, compare_exchange, symbol)
        if _needs_usdt_tmn_rate(card):
            _add_exchange_job(jobs, "nobitex", "USDTTMN")

    raw_results = _fetch_many(jobs, timeout)
    rows = [_build_row(card, raw_results, fetched_at) for card in cards]
    _persist_rows(rows, fetched_at)
    _send_periodic_telegram_summary(rows, monitor_settings, fetched_at)
    monitor_settings.mark_synced(fetched_at)

    return {
        "pollIntervalSeconds": 10,
        "syncIntervalSeconds": monitor_settings.sync_interval_minutes * 60,
        "fetchedAt": timezone.localtime(fetched_at).isoformat(),
        "rows": rows,
    }


def _fetch_many(jobs, timeout):
    results = {}
    fetch_jobs = {}
    for key, urls in jobs.items():
        if isinstance(urls, dict) and urls.get("error"):
            results[key] = {"ok": False, "error": urls["error"]}
            continue
        fetch_jobs[key] = urls

    if not fetch_jobs:
        return results

    with ThreadPoolExecutor(max_workers=min(6, max(1, len(jobs)))) as executor:
        futures = {
            executor.submit(_fetch_json_with_fallbacks, urls, timeout): key
            for key, urls in fetch_jobs.items()
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = {"ok": True, "data": future.result()}
            except Exception as exc:
                results[key] = {"ok": False, "error": str(exc)}
    return results


def _fetch_json_with_fallbacks(urls, timeout):
    if isinstance(urls, dict) and urls.get("websocket"):
        return _fetch_websocket_trade(urls, timeout)

    if isinstance(urls, str):
        urls = [urls]

    errors = []
    for url in urls:
        for attempt in range(3):
            try:
                return _fetch_json(url, timeout)
            except Exception as exc:
                errors.append(f"{url}: {exc}")
                if attempt < 2:
                    sleep(0.35 * (attempt + 1))
    raise RuntimeError("; ".join(errors))


def _fetch_json(url, timeout):
    started = perf_counter()
    headers = {"User-Agent": "PriceMonitoring/1.0"}
    if "simops.ir" in url and settings.PRICE_MONITOR.get("BITBANK_FORWARDED_FOR"):
        headers["x-forwarded-for"] = settings.PRICE_MONITOR["BITBANK_FORWARDED_FOR"]
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:200]
        raise RuntimeError(f"HTTP {exc.code} {detail}".strip()) from exc
    except URLError as exc:
        raise RuntimeError(exc.reason) from exc

    latency_ms = round((perf_counter() - started) * 1000)
    return {"payload": payload, "latencyMs": latency_ms}


def _fetch_websocket_trade(job, timeout):
    try:
        from websocket import create_connection
    except ImportError as exc:
        raise RuntimeError("websocket-client is required for Bitbank websocket pricing") from exc

    started = perf_counter()
    ws_timeout = min(timeout, settings.PRICE_MONITOR["BITBANK_WS_TIMEOUT_SECONDS"])
    headers = []
    if settings.PRICE_MONITOR.get("BITBANK_FORWARDED_FOR"):
        headers.append(f"x-forwarded-for: {settings.PRICE_MONITOR['BITBANK_FORWARDED_FOR']}")

    ws = create_connection(job["url"], timeout=ws_timeout, header=headers)
    try:
        subscribe_message = job.get("subscribeMessage")
        if subscribe_message:
            ws.send(subscribe_message)

        deadline = time.monotonic() + ws_timeout
        last_payload = None
        while time.monotonic() < deadline:
            raw_message = ws.recv()
            if isinstance(raw_message, bytes):
                raw_message = gzip.decompress(raw_message).decode("utf-8")
            try:
                payload = json.loads(raw_message)
            except json.JSONDecodeError:
                continue

            last_payload = payload
            trade = _bitbank_trade_from_ws_payload(payload)
            if trade:
                latency_ms = round((perf_counter() - started) * 1000)
                return {"payload": {"data": [trade]}, "latencyMs": latency_ms}

        raise RuntimeError(f"Bitbank websocket did not return trade data; last payload={last_payload}")
    finally:
        ws.close()


def _build_row(card, raw_results, fetched_at):
    symbol = card.symbol
    source_exchange = _source_exchange(card)
    source_key = source_exchange.lower()
    source = _extract(source_key, symbol, raw_results)
    source = _normalize_reference(symbol, source_key, source, source)
    reference_exchange = _compare_exchange(card)
    reference_key = reference_exchange.lower()
    reference = _extract(reference_key, symbol, raw_results)
    reference = _normalize_reference(symbol, reference_key, source, reference)
    if _needs_usdt_tmn_rate(card):
        usdt_tmn = _extract("nobitex", "USDTTMN", raw_results)
        usdt_tmn = _normalize_reference("USDTTMN", "nobitex", source, usdt_tmn)
        if source.price is not None and usdt_tmn.price is not None:
            source = TradePrice(source.price * usdt_tmn.price, source.timestamp, source.latency_ms)

    spread = None
    spread_abs = None
    status = "error"
    if source.price is not None and reference.price is not None and reference.price != 0:
        spread_abs = source.price - reference.price
        spread = (spread_abs / reference.price) * Decimal("100")
        GapSample.objects.create(symbol=symbol, gap_percent=spread, created_at=fetched_at)
        _delete_old_gap_samples(fetched_at)
        status = _status_for_gap(spread, card)

    errors = []
    for key in (source_key, reference_key):
        result = raw_results.get((key, symbol), {})
        if not result.get("ok"):
            errors.append(f"{key}: {result.get('error', 'fetch failed')}")

    return {
        "symbol": symbol,
        "quoteKey": _quote_key(card),
        "displaySymbol": card.display_symbol,
        "sourceExchange": source_exchange,
        "wallexPrice": _decimal_to_str(source.price),
        "referencePrice": _decimal_to_str(reference.price),
        "referenceExchange": reference_exchange,
        "normalColor": card.normal_color,
        "spreadPercent": _decimal_to_str(spread, places=4),
        "spreadAbs": _decimal_to_str(spread_abs),
        "lastTradeAt": source.timestamp or reference.timestamp,
        "lastSyncedAt": timezone.localtime(fetched_at).isoformat(),
        "status": status,
        "errors": errors,
        "fetchedAt": timezone.localtime(fetched_at).isoformat(),
    }


def _extract(exchange, symbol, raw_results):
    result = raw_results.get((exchange, symbol), {})
    if not result.get("ok"):
        return TradePrice(None, None, 0)

    data = result["data"]
    payload = data["payload"]
    latency_ms = data["latencyMs"]

    if exchange == "binance":
        trade = payload[0] if isinstance(payload, list) and payload else {}
        return TradePrice(_to_decimal(trade.get("price")), _normalize_timestamp(trade.get("time")), latency_ms)

    if exchange == "wallex":
        trades = payload.get("result", {}).get("latestTrades", [])
        trade = trades[0] if trades else {}
        return TradePrice(_to_decimal(trade.get("price")), _normalize_timestamp(trade.get("timestamp")), latency_ms)

    if exchange == "bitbank":
        trade = _bitbank_latest_trade(payload.get("data", []))
        price = _to_decimal(trade.get("price"))
        timestamp = trade.get("ctime") or trade.get("time")
        return TradePrice(price, _normalize_timestamp(timestamp), latency_ms)

    trades = payload.get("trades", [])
    trade = trades[0] if trades else {}
    return TradePrice(_to_decimal(trade.get("price")), _normalize_timestamp(trade.get("time")), latency_ms)


def _normalize_reference(symbol, reference_key, wallex, reference):
    if reference.price is None:
        return reference
    if reference_key == "bitbank" and _is_fiat_symbol(symbol):
        return TradePrice(_integer_toman(reference.price / Decimal("10")), reference.timestamp, reference.latency_ms)
    if reference_key == "nobitex" and symbol.endswith(("TMN", "IRR")):
        return TradePrice(reference.price / Decimal("10"), reference.timestamp, reference.latency_ms)
    if reference_key == "nobitex" and symbol.endswith("USDT") and symbol != "USDTTMN":
        return TradePrice(reference.price / Decimal("10"), reference.timestamp, reference.latency_ms)
    return reference


def _is_fiat_symbol(symbol):
    return symbol.endswith(("TMN", "IRT", "IRR"))


def _integer_toman(value):
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _bitbank_latest_trade(trades):
    if not isinstance(trades, list) or not trades:
        return {}
    return max(
        (trade for trade in trades if isinstance(trade, dict)),
        key=lambda trade: int(trade.get("ctime") or trade.get("time") or trade.get("id") or 0),
        default={},
    )


def _bitbank_trade_from_ws_payload(payload):
    candidates = _walk_trade_candidates(payload)
    for item in candidates:
        price = (
            item.get("price")
            or item.get("p")
            or item.get("last")
            or item.get("lastPrice")
            or item.get("close")
        )
        if _to_decimal(price) is None:
            continue
        timestamp = item.get("ctime") or item.get("time") or item.get("timestamp") or item.get("ts")
        return {"price": price, "ctime": timestamp}
    return {}


def _walk_trade_candidates(value):
    if isinstance(value, dict):
        if any(key in value for key in ("price", "p", "last", "lastPrice", "close")):
            yield value
        for child in value.values():
            yield from _walk_trade_candidates(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_trade_candidates(child)


def _to_decimal(value):
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _decimal_to_str(value, places=None):
    if value is None:
        return None
    if places is not None:
        value = value.quantize(Decimal(1).scaleb(-places))
    return format(value.normalize(), "f")


def _display_symbol(symbol):
    if symbol.endswith("USDT"):
        return f"{symbol[:-4]} / USDT"
    if symbol.endswith("TMN"):
        return f"{symbol[:-3]} / TMN"
    if symbol.endswith("IRR"):
        return f"{symbol[:-3]} / TMN"
    return symbol


def _nobitex_symbol(symbol):
    if symbol.endswith("USDT") and symbol != "USDTTMN":
        return f"{symbol[:-4]}IRT"
    if symbol.endswith(("TMN", "IRR")):
        return f"{symbol[:-3]}IRT"
    return symbol


def _wallex_symbol(symbol):
    if symbol.endswith("IRR"):
        return f"{symbol[:-3]}TMN"
    return symbol


def _bitbank_symbol(symbol):
    if symbol in {"USDTTMN", "USDTIRT", "USDTIRR"}:
        return "usdtirr"
    if symbol.endswith(("TMN", "IRT", "IRR")):
        return f"{symbol[:-3]}IRR".lower()
    return symbol.lower()


def _add_exchange_job(jobs, exchange, symbol):
    if exchange == "wallex":
        jobs[("wallex", symbol)] = WALLEX_URL.format(symbol=_wallex_symbol(symbol))
    elif exchange == "nobitex":
        jobs[("nobitex", symbol)] = NOBITEX_URL.format(symbol=_nobitex_symbol(symbol))
    elif exchange == "binance" and symbol.endswith("USDT"):
        jobs[("binance", symbol)] = [url.format(symbol=symbol) for url in BINANCE_URLS]
    elif exchange == "bitbank":
        ws_url = settings.PRICE_MONITOR.get("BITBANK_WS_URL", "").strip()
        if ws_url:
            subscribe_message = _bitbank_ws_subscribe_message(symbol)
            jobs[("bitbank", symbol)] = {
                "websocket": True,
                "url": ws_url,
                "subscribeMessage": subscribe_message,
            }
            return

        base_url = settings.PRICE_MONITOR["BITBANK_REST_URL"].rstrip("/")
        if not base_url:
            jobs[("bitbank", symbol)] = {
                "error": "BITBANK_REST_URL is not configured for real Bitbank market data"
            }
            return
        if "simops.ir" in base_url and not settings.PRICE_MONITOR.get("BITBANK_ALLOW_SIMOPS"):
            jobs[("bitbank", symbol)] = {
                "error": "BITBANK_REST_URL points to simops test data; set the real Bitbank market-data URL"
            }
            return
        endpoint = settings.PRICE_MONITOR["BITBANK_TRADES_ENDPOINT"]
        jobs[("bitbank", symbol)] = f"{base_url}{endpoint}?symbol={_bitbank_symbol(symbol)}"


def _bitbank_ws_subscribe_message(symbol):
    template = settings.PRICE_MONITOR.get("BITBANK_WS_SUBSCRIBE_MESSAGE", "").strip()
    if not template and "bitbank3.com" in settings.PRICE_MONITOR.get("BITBANK_WS_URL", ""):
        template = (
            '{{"event":"sub","params":{{"channel":"market_{symbol}_ticker",'
            '"cb_id":"{symbol}"}}}}'
        )
    if not template:
        return ""
    return template.format(
        symbol=_bitbank_symbol(symbol),
        symbol_upper=_bitbank_symbol(symbol).upper(),
        raw_symbol=symbol,
    )


def _source_exchange(card):
    return card.reference_exchange


def _needs_usdt_tmn_rate(card):
    return (
        card.reference_exchange == "Bitbank"
        and card.compare_exchange == "Nobitex"
        and card.symbol.endswith("USDT")
        and card.symbol != "USDTTMN"
    )


def _quote_key(card):
    return f"{_source_exchange(card)}:{card.symbol}:{_compare_exchange(card)}"


def _compare_exchange(card):
    if card.symbol.endswith(("TMN", "IRR")) and card.reference_exchange != "Bitbank":
        return "Nobitex"
    return card.compare_exchange


def _normalize_timestamp(value):
    if value is None:
        return None

    if isinstance(value, (int, float)) or str(value).isdigit():
        stamp = int(value)
        if stamp < 10_000_000_000:
            stamp *= 1000
        trade_time = datetime.fromtimestamp(stamp / 1000, tz=datetime_timezone.utc)
        return timezone.localtime(trade_time).isoformat()

    text = str(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        trade_time = datetime.fromisoformat(text)
    except ValueError:
        return str(value)

    if trade_time.tzinfo is None:
        trade_time = trade_time.replace(tzinfo=datetime_timezone.utc)
    return timezone.localtime(trade_time).isoformat()


def _delete_old_gap_samples(created_at):
    cutoff = created_at - timedelta(seconds=HISTORY_WINDOW_SECONDS)
    GapSample.objects.filter(created_at__lt=cutoff).delete()


def _status_for_gap(gap, card=None):
    if gap is None:
        return "error"

    if card is not None:
        matched = _matching_threshold_status(gap, card)
        if matched is not None:
            return matched

    return _fallback_status_for_gap(gap)


def _matching_threshold_status(gap, card):
    if card.pk is None:
        return None

    priority = {"danger": 3, "warning": 2, "normal": 1}
    matched = []
    for rule in card.thresholds.filter(enabled=True):
        if _compare_gap(gap, rule.operator, rule.threshold_percent):
            matched.append(rule.category)

    if not matched:
        return None
    return max(matched, key=lambda category: priority.get(category, 0))


def _compare_gap(gap, operator, threshold):
    if operator == ">=":
        return gap >= threshold
    if operator == ">":
        return gap > threshold
    if operator == "<=":
        return gap <= threshold
    if operator == "<":
        return gap < threshold
    if operator == "==":
        return gap == threshold
    return False


def _fallback_status_for_gap(gap):
    absolute_gap = abs(gap)
    danger_threshold = _positive_decimal_env("GAP_DANGER_PERCENT", settings.PRICE_MONITOR["GAP_DANGER_PERCENT"])
    warn_threshold = _positive_decimal_env("GAP_WARN_PERCENT", settings.PRICE_MONITOR["GAP_WARN_PERCENT"])
    if warn_threshold > danger_threshold:
        warn_threshold, danger_threshold = danger_threshold, warn_threshold

    if absolute_gap >= danger_threshold:
        return "danger"
    if absolute_gap >= warn_threshold:
        return "warning"
    return "normal"


def _configured_symbols():
    raw_symbols = _env_value(
        "WALLEX_SYMBOLS",
        ",".join(settings.PRICE_MONITOR["WALLEX_SYMBOLS"]),
    )
    return [
        symbol.strip().upper()
        for symbol in raw_symbols.split(",")
        if symbol.strip()
    ]


def _configured_cards(visible_only):
    try:
        queryset = MonitorCard.objects.prefetch_related("thresholds").order_by("display_order", "symbol")
        if visible_only:
            queryset = queryset.filter(show_on_monitor=True)
        cards = list(queryset)
        if cards:
            return cards

        return _seed_default_cards()
    except (OperationalError, ProgrammingError, ImproperlyConfigured):
        return [_fallback_card(symbol) for symbol in _configured_symbols()]


def _seed_default_cards():
    cards = []
    for index, symbol in enumerate(_configured_symbols(), start=1):
        card, created = MonitorCard.objects.get_or_create(
            symbol=symbol,
            reference_exchange="Wallex",
            compare_exchange="Nobitex" if symbol == "USDTTMN" else "Binance",
            defaults={
                "display_order": index,
            },
        )
        if created:
            _create_default_thresholds(card)
        cards.append(card)
    return cards


def _create_default_thresholds(card):
    card.thresholds.bulk_create(
        [
            card.thresholds.model(card=card, category="warning", bound="upper", operator=">=", threshold_percent=1),
            card.thresholds.model(card=card, category="warning", bound="lower", operator="<=", threshold_percent=-1),
            card.thresholds.model(card=card, category="danger", bound="upper", operator=">=", threshold_percent=3),
            card.thresholds.model(card=card, category="danger", bound="lower", operator="<=", threshold_percent=-3),
        ]
    )


def _fallback_card(symbol):
    return MonitorCard(
        symbol=symbol,
        display_order=1,
        compare_exchange="Nobitex" if symbol == "USDTTMN" else "Binance",
        normal_color="green",
    )


def _monitor_settings():
    try:
        return MonitorSettings.load()
    except (OperationalError, ProgrammingError):
        return MonitorSettings(sync_interval_minutes=max(1, settings.PRICE_MONITOR["POLL_INTERVAL_SECONDS"] // 60))


def _sync_is_due(monitor_settings):
    if monitor_settings.last_synced_at is None:
        return True
    next_sync_at = monitor_settings.last_synced_at + timedelta(minutes=monitor_settings.sync_interval_minutes)
    return timezone.now() >= next_sync_at


def _decimal_env(key, default):
    try:
        return Decimal(_env_value(key, str(default)))
    except (InvalidOperation, ValueError):
        return default


def _positive_decimal_env(key, default):
    return abs(_decimal_env(key, default))


def _env_value(key, default):
    env_path = settings.BASE_DIR / ".env"
    if not env_path.exists():
        return os.environ.get(key, default)

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        env_key, value = line.split("=", 1)
        if env_key.strip() == key:
            return value.strip().strip('"').strip("'")
    return default


@transaction.atomic
def _persist_rows(rows, fetched_at):
    monitor_settings = _monitor_settings()
    for row in rows:
        existing = MarketQuote.objects.filter(symbol=row["quoteKey"]).first()
        wallex_price = _to_decimal(row["wallexPrice"])
        reference_price = _to_decimal(row["referencePrice"])
        both_prices_failed = wallex_price is None and reference_price is None and row["errors"]

        if existing is not None and both_prices_failed:
            existing.reference_exchange = row["referenceExchange"]
            existing.status = "error"
            existing.errors = row["errors"]
            existing.save(update_fields=["reference_exchange", "status", "errors", "updated_at"])
            continue

        previous_status = existing.status if existing is not None else None
        quote, _ = MarketQuote.objects.update_or_create(
            symbol=row["quoteKey"],
            defaults={
                "display_symbol": row["displaySymbol"],
                "wallex_price": wallex_price,
                "reference_price": reference_price,
                "reference_exchange": row["referenceExchange"],
                "gap_percent": _to_decimal(row["spreadPercent"]),
                "gap_stddev_percent": None,
                "gap_abs": _to_decimal(row["spreadAbs"]),
                "last_trade_at": row["lastTradeAt"],
                "status": row["status"],
                "errors": row["errors"],
                "fetched_at": fetched_at,
            },
        )


def _quote_to_row(card, quote):
    symbol = card.symbol
    if quote is None:
        return {
            "symbol": symbol,
            "quoteKey": _quote_key(card),
            "displaySymbol": card.display_symbol,
            "sourceExchange": _source_exchange(card),
            "wallexPrice": None,
            "referencePrice": None,
            "referenceExchange": _compare_exchange(card),
            "normalColor": card.normal_color,
            "spreadPercent": None,
            "spreadAbs": None,
            "lastTradeAt": None,
            "lastSyncedAt": None,
            "status": "error",
            "errors": ["waiting for celery refresh"],
        }

    return {
        "symbol": symbol,
        "quoteKey": _quote_key(card),
        "displaySymbol": quote.display_symbol,
        "sourceExchange": _source_exchange(card),
        "wallexPrice": _decimal_to_str(quote.wallex_price),
        "referencePrice": _decimal_to_str(quote.reference_price),
        "referenceExchange": quote.reference_exchange,
        "normalColor": card.normal_color,
        "spreadPercent": _decimal_to_str(quote.gap_percent, places=4),
        "spreadAbs": _decimal_to_str(quote.gap_abs),
        "lastTradeAt": quote.last_trade_at,
        "lastSyncedAt": timezone.localtime(quote.fetched_at).isoformat(),
        "status": _status_for_gap(quote.gap_percent, card) if quote.gap_percent is not None else quote.status,
        "errors": quote.errors,
    }


def _send_periodic_telegram_summary(rows, monitor_settings, fetched_at):
    if not monitor_settings.pk or not monitor_settings.telegram_alerts_enabled:
        return
    if not monitor_settings.telegram_bot_token or not monitor_settings.telegram_chat_id:
        return
    if not _telegram_summary_is_due(monitor_settings, fetched_at):
        return

    alert_rows = [
        row
        for row in rows
        if row["status"] in {"warning", "danger"} and not row["errors"]
    ]
    if not alert_rows:
        monitor_settings.telegram_last_summary_at = fetched_at
        monitor_settings.save(update_fields=["telegram_last_summary_at"])
        return

    message = _telegram_summary_message(alert_rows, fetched_at)
    transaction.on_commit(lambda: _send_telegram_summary_after_commit(monitor_settings.pk, message, fetched_at))


def _telegram_summary_is_due(monitor_settings, fetched_at):
    if monitor_settings.telegram_last_summary_at is None:
        return True
    next_summary_at = monitor_settings.telegram_last_summary_at + timedelta(
        minutes=monitor_settings.telegram_summary_interval_minutes
    )
    return fetched_at >= next_summary_at


def _telegram_summary_message(rows, fetched_at):
    lines = [
        "Price Monitoring alerts",
        f"Synced at: {timezone.localtime(fetched_at).strftime('%H:%M')}",
        "",
    ]
    for row in rows:
        marker = "DANGER" if row["status"] == "danger" else "WARN"
        gap = _decimal_to_str(_to_decimal(row["spreadPercent"]), places=2) or "-"
        lines.append(f"{marker} | {row['displaySymbol']} | Gap: {gap}%")
        lines.append(f"{row.get('sourceExchange', 'Wallex')}: {row['wallexPrice'] or '-'}")
        lines.append(f"{row['referenceExchange']}: {row['referencePrice'] or '-'}")
        lines.append("")
    return "\n".join(lines).strip()


def _send_telegram_summary_after_commit(monitor_settings_id, message, fetched_at):
    try:
        monitor_settings = MonitorSettings.objects.get(pk=monitor_settings_id)
    except MonitorSettings.DoesNotExist:
        return

    sent = _send_telegram_alert(monitor_settings, message)
    if sent:
        monitor_settings.telegram_last_summary_at = fetched_at
        monitor_settings.save(update_fields=["telegram_last_summary_at"])


def _send_telegram_alert(monitor_settings, message):
    if not monitor_settings.telegram_bot_token or not monitor_settings.telegram_chat_id:
        return

    url = f"https://api.telegram.org/bot{monitor_settings.telegram_bot_token}/sendMessage"
    payload = urlencode({"chat_id": monitor_settings.telegram_chat_id, "text": message}).encode("utf-8")
    request = Request(url, data=payload, headers={"User-Agent": "PriceMonitoring/1.0"})
    try:
        with urlopen(request, timeout=settings.PRICE_MONITOR["REQUEST_TIMEOUT_SECONDS"]):
            return True
    except Exception:
        return False
