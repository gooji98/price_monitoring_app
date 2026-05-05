from pathlib import Path
from decimal import Decimal
import os


BASE_DIR = Path(__file__).resolve().parent.parent


def load_env(path):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env(BASE_DIR / ".env")


def decimal_env(key, default):
    try:
        return Decimal(os.environ.get(key, default))
    except Exception:
        return Decimal(default)


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-price-monitor-secret")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [host.strip() for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")]

INSTALLED_APPS = [
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "marketwatch",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "price_monitor.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

WSGI_APPLICATION = "price_monitor.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "price_monitoring_board"),
        "USER": os.environ.get("DB_USER", "postgres"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "22573312"),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

LANGUAGE_CODE = "fa-ir"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = os.environ.get("DJANGO_STATIC_ROOT", BASE_DIR / "staticfiles")
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

JAZZMIN_SETTINGS = {
    "site_title": "Price Monitoring Admin",
    "site_header": "Price Monitoring",
    "site_brand": "Price Monitoring",
    "welcome_sign": "مدیریت مانیتور قیمت",
    "copyright": "Price Monitoring",
    "show_sidebar": True,
    "navigation_expanded": True,
    "order_with_respect_to": ["marketwatch"],
    "icons": {
        "marketwatch.MonitorCard": "fas fa-chart-line",
        "marketwatch.ThresholdRule": "fas fa-sliders-h",
        "marketwatch.MonitorSettings": "fas fa-cog",
        "marketwatch.MarketQuote": "fas fa-database",
        "marketwatch.GapSample": "fas fa-history",
    },
}

PRICE_MONITOR = {
    "WALLEX_SYMBOLS": [
        symbol.strip().upper()
        for symbol in os.environ.get("WALLEX_SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT,USDTTMN").split(",")
        if symbol.strip()
    ],
    "POLL_INTERVAL_SECONDS": max(1, int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))),
    "REQUEST_TIMEOUT_SECONDS": max(1, int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "8"))),
    "GAP_WARN_PERCENT": decimal_env("GAP_WARN_PERCENT", "1"),
    "GAP_DANGER_PERCENT": decimal_env("GAP_DANGER_PERCENT", "3"),
    "BITBANK_REST_URL": os.environ.get("BITBANK_REST_URL", ""),
    "BITBANK_ORDERBOOK_ENDPOINT": os.environ.get("BITBANK_ORDERBOOK_ENDPOINT", "/open/api/market_dept"),
    "BITBANK_TICKER_ENDPOINT": os.environ.get("BITBANK_TICKER_ENDPOINT", "/open/api/get_ticker"),
    "BITBANK_TRADES_ENDPOINT": os.environ.get("BITBANK_TRADES_ENDPOINT", "/open/api/get_trades"),
    "BITBANK_FORWARDED_FOR": os.environ.get("BITBANK_FORWARDED_FOR", ""),
    "BITBANK_ALLOW_SIMOPS": os.environ.get("BITBANK_ALLOW_SIMOPS", "0") == "1",
    "BITBANK_WS_URL": os.environ.get("BITBANK_WS_URL", ""),
    "BITBANK_WS_SUBSCRIBE_MESSAGE": os.environ.get("BITBANK_WS_SUBSCRIBE_MESSAGE", ""),
    "BITBANK_WS_TIMEOUT_SECONDS": max(1, int(os.environ.get("BITBANK_WS_TIMEOUT_SECONDS", "8"))),
}

CELERY_DIR = BASE_DIR / ".celery"
CELERY_DIR.mkdir(exist_ok=True)
(CELERY_DIR / "in").mkdir(exist_ok=True)
(CELERY_DIR / "out").mkdir(exist_ok=True)
(CELERY_DIR / "broker").mkdir(exist_ok=True)
(CELERY_DIR / "processed").mkdir(exist_ok=True)

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "filesystem://")
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "data_folder_in": str(CELERY_DIR / "broker"),
    "data_folder_out": str(CELERY_DIR / "broker"),
    "data_folder_processed": str(CELERY_DIR / "processed"),
}
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND")
CELERY_TASK_IGNORE_RESULT = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "refresh-market-prices-check-every-second": {
        "task": "marketwatch.tasks.refresh_market_prices",
        "schedule": 1.0,
    }
}
