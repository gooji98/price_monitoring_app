from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone


class MonitorCard(models.Model):
    REFERENCE_EXCHANGES = [
        ("Wallex", "Wallex"),
        ("Bitbank", "Bitbank"),
    ]
    COMPARE_EXCHANGES = [
        ("Binance", "Binance"),
        ("Nobitex", "Nobitex"),
        ("Wallex", "Wallex"),
        ("Bitbank", "Bitbank"),
    ]
    COLOR_CHOICES = [
        ("green", "سبز"),
        ("blue", "آبی"),
        ("gray", "خاکستری"),
        ("yellow", "زرد"),
        ("red", "قرمز"),
    ]

    symbol = models.CharField("نام کارت", max_length=24, help_text="مثلا BTCUSDT")
    reference_exchange = models.CharField("قیمت مرجع", max_length=32, choices=REFERENCE_EXCHANGES, default="Wallex")
    compare_exchange = models.CharField("مقایسه با", max_length=32, choices=COMPARE_EXCHANGES, default="Binance")
    show_on_monitor = models.BooleanField("نمایش در مانیتور؟", default=True)
    display_order = models.PositiveIntegerField("ترتیب نمایش", default=1)
    normal_color = models.CharField("رنگ کارت در حالت عادی", max_length=16, choices=COLOR_CHOICES, default="green")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "symbol"]
        constraints = [
            models.UniqueConstraint(
                fields=["symbol", "reference_exchange", "compare_exchange"],
                name="unique_monitor_card_route",
            )
        ]
        verbose_name = "کارت مانیتور"
        verbose_name_plural = "کارت‌های مانیتور"

    def __str__(self):
        return self.display_symbol

    def clean(self):
        if self.symbol:
            self.symbol = self.symbol.strip().upper().replace(" / ", "").replace("/", "").replace(" ", "")
        if self.symbol.endswith(("TMN", "IRR")) and self.reference_exchange != "Bitbank":
            self.compare_exchange = "Nobitex"
        if (
            self.reference_exchange == "Wallex"
            and self.symbol.endswith("USDT")
            and self.compare_exchange == "Nobitex"
            and self.symbol != "USDTTMN"
        ):
            raise ValidationError({"compare_exchange": "برای نمادهای USDT از Binance استفاده کن."})
        if self.reference_exchange == self.compare_exchange:
            raise ValidationError({"compare_exchange": "صرافی مرجع و صرافی مقایسه نباید یکی باشند."})

    @property
    def display_symbol(self):
        if self.symbol.endswith("USDT"):
            return f"{self.symbol[:-4]}USDT"
        if self.symbol.endswith(("TMN", "IRT", "IRR")):
            return f"{self.symbol[:-3]}IRT"
        return self.symbol


class ThresholdRule(models.Model):
    CATEGORY_CHOICES = [
        ("normal", "عادی"),
        ("warning", "در آستانه خطر"),
        ("danger", "خطر"),
    ]
    BOUND_CHOICES = [
        ("upper", "آستانه بالا"),
        ("lower", "آستانه پایین"),
    ]
    OPERATOR_CHOICES = [
        (">=", "بزرگ‌تر یا مساوی"),
        (">", "بزرگ‌تر"),
        ("<=", "کوچک‌تر یا مساوی"),
        ("<", "کوچک‌تر"),
        ("==", "مساوی"),
    ]

    card = models.ForeignKey(MonitorCard, verbose_name="کارت", related_name="thresholds", on_delete=models.CASCADE)
    category = models.CharField("کتگوری", max_length=16, choices=CATEGORY_CHOICES)
    bound = models.CharField("نوع آستانه", max_length=16, choices=BOUND_CHOICES, default="upper")
    operator = models.CharField("عملگر", max_length=2, choices=OPERATOR_CHOICES, default=">=")
    threshold_percent = models.DecimalField("آستانه گپ (%)", max_digits=18, decimal_places=8)
    enabled = models.BooleanField("فعال", default=True)

    class Meta:
        ordering = ["card", "category", "bound"]
        verbose_name = "قانون آستانه"
        verbose_name_plural = "قوانین آستانه"

    def __str__(self):
        return f"{self.card} | gap {self.operator} {self.threshold_percent}% -> {self.get_category_display()}"


class MonitorSettings(models.Model):
    sync_interval_minutes = models.PositiveIntegerField("دقایق سینک / داده‌گیری", default=1)
    sync_interval_seconds = models.PositiveIntegerField("ثانیه‌های سینک / داده‌گیری", default=60)
    last_synced_at = models.DateTimeField("آخرین داده‌گیری", null=True, blank=True, editable=False)
    telegram_alerts_enabled = models.BooleanField("Telegram alerts enabled", default=False)
    telegram_bot_token = models.CharField("Telegram bot token", max_length=128, blank=True)
    telegram_chat_id = models.CharField("Telegram chat id", max_length=64, blank=True)
    telegram_summary_interval_minutes = models.PositiveIntegerField("Telegram summary interval minutes", default=5)
    telegram_last_summary_at = models.DateTimeField(
        "Telegram last summary at",
        null=True,
        blank=True,
        editable=False,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "تنظیمات مانیتور"
        verbose_name_plural = "تنظیمات مانیتور"

    def __str__(self):
        return f"هر {self.sync_interval_seconds} ثانیه"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"sync_interval_minutes": 1, "sync_interval_seconds": 60})
        return obj

    def mark_synced(self, synced_at=None):
        self.last_synced_at = synced_at or timezone.now()
        self.save(update_fields=["last_synced_at"])


class MarketQuote(models.Model):
    symbol = models.CharField(max_length=96, unique=True)
    display_symbol = models.CharField(max_length=32)
    wallex_price = models.DecimalField(max_digits=28, decimal_places=12, null=True, blank=True)
    reference_price = models.DecimalField(max_digits=28, decimal_places=12, null=True, blank=True)
    reference_exchange = models.CharField(max_length=32)
    gap_percent = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    gap_stddev_percent = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    gap_abs = models.DecimalField(max_digits=28, decimal_places=12, null=True, blank=True)
    last_trade_at = models.CharField(max_length=64, null=True, blank=True)
    status = models.CharField(max_length=16, default="error")
    errors = models.JSONField(default=list, blank=True)
    fetched_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["symbol"]


class GapSample(models.Model):
    symbol = models.CharField(max_length=24, db_index=True)
    gap_percent = models.DecimalField(max_digits=18, decimal_places=8)
    created_at = models.DateTimeField(db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["symbol", "created_at"], name="marketwatch_symbol_6ef51d_idx"),
        ]
