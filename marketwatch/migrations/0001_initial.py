from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="GapSample",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("symbol", models.CharField(db_index=True, max_length=24)),
                ("gap_percent", models.DecimalField(decimal_places=8, max_digits=18)),
                ("created_at", models.DateTimeField(db_index=True)),
            ],
            options={
                "indexes": [models.Index(fields=["symbol", "created_at"], name="marketwatch_symbol_6ef51d_idx")],
            },
        ),
        migrations.CreateModel(
            name="MarketQuote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("symbol", models.CharField(max_length=24, unique=True)),
                ("display_symbol", models.CharField(max_length=32)),
                ("wallex_price", models.DecimalField(blank=True, decimal_places=12, max_digits=28, null=True)),
                ("reference_price", models.DecimalField(blank=True, decimal_places=12, max_digits=28, null=True)),
                ("reference_exchange", models.CharField(max_length=32)),
                ("gap_percent", models.DecimalField(blank=True, decimal_places=8, max_digits=18, null=True)),
                ("gap_stddev_percent", models.DecimalField(blank=True, decimal_places=8, max_digits=18, null=True)),
                ("gap_abs", models.DecimalField(blank=True, decimal_places=12, max_digits=28, null=True)),
                ("last_trade_at", models.CharField(blank=True, max_length=64, null=True)),
                ("status", models.CharField(default="error", max_length=16)),
                ("errors", models.JSONField(blank=True, default=list)),
                ("fetched_at", models.DateTimeField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["symbol"],
            },
        ),
    ]
