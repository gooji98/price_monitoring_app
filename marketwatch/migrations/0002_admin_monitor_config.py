from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_monitor_config(apps, schema_editor):
    MonitorCard = apps.get_model("marketwatch", "MonitorCard")
    MonitorSettings = apps.get_model("marketwatch", "MonitorSettings")
    ThresholdRule = apps.get_model("marketwatch", "ThresholdRule")

    MonitorSettings.objects.get_or_create(pk=1, defaults={"sync_interval_minutes": 1})

    symbols = settings.PRICE_MONITOR.get("WALLEX_SYMBOLS", [])
    for index, symbol in enumerate(symbols, start=1):
        card, created = MonitorCard.objects.get_or_create(
            symbol=symbol,
            defaults={
                "display_order": index,
                "compare_exchange": "Nobitex" if symbol == "USDTTMN" else "Binance",
            },
        )
        if created:
            ThresholdRule.objects.bulk_create(
                [
                    ThresholdRule(card=card, category="warning", bound="upper", operator=">=", threshold_percent=1),
                    ThresholdRule(card=card, category="warning", bound="lower", operator="<=", threshold_percent=-1),
                    ThresholdRule(card=card, category="danger", bound="upper", operator=">=", threshold_percent=3),
                    ThresholdRule(card=card, category="danger", bound="lower", operator="<=", threshold_percent=-3),
                ]
            )


class Migration(migrations.Migration):
    dependencies = [
        ("marketwatch", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="MonitorCard",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("symbol", models.CharField(help_text="مثلا BTCUSDT", max_length=24, unique=True, verbose_name="نام کارت")),
                (
                    "reference_exchange",
                    models.CharField(
                        choices=[("Wallex", "Wallex")],
                        default="Wallex",
                        max_length=32,
                        verbose_name="قیمت مرجع",
                    ),
                ),
                (
                    "compare_exchange",
                    models.CharField(
                        choices=[("Binance", "Binance"), ("Nobitex", "Nobitex")],
                        default="Binance",
                        max_length=32,
                        verbose_name="مقایسه با",
                    ),
                ),
                ("show_on_monitor", models.BooleanField(default=True, verbose_name="نمایش در مانیتور؟")),
                ("display_order", models.PositiveIntegerField(default=1, verbose_name="ترتیب نمایش")),
                (
                    "normal_color",
                    models.CharField(
                        choices=[
                            ("green", "سبز"),
                            ("blue", "آبی"),
                            ("gray", "خاکستری"),
                            ("yellow", "زرد"),
                            ("red", "قرمز"),
                        ],
                        default="green",
                        max_length=16,
                        verbose_name="رنگ کارت در حالت عادی",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "کارت مانیتور",
                "verbose_name_plural": "کارت‌های مانیتور",
                "ordering": ["display_order", "symbol"],
            },
        ),
        migrations.CreateModel(
            name="MonitorSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sync_interval_minutes", models.PositiveIntegerField(default=1, verbose_name="دقایق سینک / داده‌گیری")),
                ("last_synced_at", models.DateTimeField(blank=True, editable=False, null=True, verbose_name="آخرین داده‌گیری")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "تنظیمات مانیتور",
                "verbose_name_plural": "تنظیمات مانیتور",
            },
        ),
        migrations.CreateModel(
            name="ThresholdRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "category",
                    models.CharField(
                        choices=[("normal", "عادی"), ("warning", "در آستانه خطر"), ("danger", "خطر")],
                        max_length=16,
                        verbose_name="کتگوری",
                    ),
                ),
                (
                    "bound",
                    models.CharField(
                        choices=[("upper", "آستانه بالا"), ("lower", "آستانه پایین")],
                        default="upper",
                        max_length=16,
                        verbose_name="نوع آستانه",
                    ),
                ),
                (
                    "operator",
                    models.CharField(
                        choices=[
                            (">=", "بزرگ‌تر یا مساوی"),
                            (">", "بزرگ‌تر"),
                            ("<=", "کوچک‌تر یا مساوی"),
                            ("<", "کوچک‌تر"),
                            ("==", "مساوی"),
                        ],
                        default=">=",
                        max_length=2,
                        verbose_name="عملگر",
                    ),
                ),
                ("threshold_percent", models.DecimalField(decimal_places=8, max_digits=18, verbose_name="آستانه گپ (%)")),
                ("enabled", models.BooleanField(default=True, verbose_name="فعال")),
                (
                    "card",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="thresholds",
                        to="marketwatch.monitorcard",
                        verbose_name="کارت",
                    ),
                ),
            ],
            options={
                "verbose_name": "قانون آستانه",
                "verbose_name_plural": "قوانین آستانه",
                "ordering": ["card", "category", "bound"],
            },
        ),
        migrations.RunPython(seed_monitor_config, migrations.RunPython.noop),
    ]
