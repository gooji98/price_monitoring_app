from django.contrib import admin

from .models import GapSample, MarketQuote, MonitorCard, MonitorSettings, TelegramSubscriber, ThresholdRule


class ThresholdRuleInline(admin.TabularInline):
    model = ThresholdRule
    extra = 3
    fields = ("metric", "category", "bound", "operator", "threshold_percent", "enabled")
    readonly_fields = ("metric",)

    @admin.display(description="شاخص")
    def metric(self, obj):
        return "gap"


@admin.register(MonitorCard)
class MonitorCardAdmin(admin.ModelAdmin):
    list_display = (
        "symbol",
        "display_label",
        "reference_exchange",
        "compare_exchange",
        "show_on_monitor",
        "display_order",
        "normal_color",
        "spread_threshold_percent",
        "spread_fast_threshold_percent",
        "spread_alert_color",
    )
    list_editable = ("show_on_monitor", "display_order", "normal_color", "spread_threshold_percent", "spread_fast_threshold_percent", "spread_alert_color")
    list_filter = ("show_on_monitor", "reference_exchange", "compare_exchange", "normal_color", "spread_alert_color")
    search_fields = ("symbol",)
    inlines = [ThresholdRuleInline]
    fieldsets = (
        (
            "General",
            {
                "fields": (
                    "symbol",
                    "reference_exchange",
                    "compare_exchange",
                    "show_on_monitor",
                    "display_order",
                    "normal_color",
                )
            },
        ),
        (
            "Bitbank spread alert",
            {
                "fields": (
                    "spread_threshold_percent",
                    "spread_fast_threshold_percent",
                    "spread_alert_color",
                    "spread_siren_enabled",
                ),
                "description": "These fields are used when the source exchange is Bitbank.",
            },
        ),
    )

    @admin.display(description="نمایش")
    def display_label(self, obj):
        return obj.display_symbol

    def save_model(self, request, obj, form, change):
        obj.symbol = obj.symbol.strip().upper().replace(" / ", "").replace("/", "").replace(" ", "")
        if obj.symbol.endswith(("TMN", "IRR")) and obj.reference_exchange != "Bitbank":
            obj.compare_exchange = "Nobitex"
        super().save_model(request, obj, form, change)
        if not change and not obj.thresholds.exists():
            ThresholdRule.objects.bulk_create(
                [
                    ThresholdRule(card=obj, category="warning", bound="upper", operator=">=", threshold_percent=1),
                    ThresholdRule(card=obj, category="warning", bound="lower", operator="<=", threshold_percent=-1),
                    ThresholdRule(card=obj, category="danger", bound="upper", operator=">=", threshold_percent=3),
                    ThresholdRule(card=obj, category="danger", bound="lower", operator="<=", threshold_percent=-3),
                ]
            )


@admin.register(ThresholdRule)
class ThresholdRuleAdmin(admin.ModelAdmin):
    list_display = ("card", "metric", "category", "bound", "operator", "threshold_percent", "enabled")
    list_filter = ("category", "bound", "operator", "enabled")
    search_fields = ("card__symbol",)

    @admin.display(description="شاخص")
    def metric(self, obj):
        return "gap"


@admin.register(MonitorSettings)
class MonitorSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "sync_interval_seconds",
        "bitbank_spread_interval_seconds",
        "telegram_alerts_enabled",
        "last_synced_at",
        "last_spread_synced_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("sync_interval_seconds", "bitbank_spread_interval_seconds", "last_synced_at", "last_spread_synced_at")}),
        (
            "Telegram alerts",
            {
                "fields": (
                    "telegram_alerts_enabled",
                    "telegram_bot_token",
                    "telegram_chat_id",
                    "telegram_update_offset",
                    "telegram_summary_interval_minutes",
                    "telegram_last_summary_at",
                )
            },
        ),
    )
    readonly_fields = ("last_synced_at", "last_spread_synced_at", "telegram_update_offset", "telegram_last_summary_at")

    def has_add_permission(self, request):
        return not MonitorSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TelegramSubscriber)
class TelegramSubscriberAdmin(admin.ModelAdmin):
    list_display = ("chat_id", "display_name", "chat_type", "is_active", "last_seen_at", "updated_at")
    list_filter = ("is_active", "chat_type")
    search_fields = ("chat_id", "title", "username", "first_name", "last_name")
    readonly_fields = ("started_at", "last_seen_at", "updated_at")

    @admin.display(description="Name")
    def display_name(self, obj):
        return obj.title or obj.username or " ".join([obj.first_name, obj.last_name]).strip()


@admin.register(MarketQuote)
class MarketQuoteAdmin(admin.ModelAdmin):
    list_display = ("symbol", "display_symbol", "reference_exchange", "gap_percent", "bitbank_spread_percent", "bitbank_spread_abs", "bitbank_spread_status", "status", "fetched_at")
    list_filter = ("reference_exchange", "status")
    search_fields = ("symbol", "display_symbol")
    readonly_fields = [field.name for field in MarketQuote._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(GapSample)
class GapSampleAdmin(admin.ModelAdmin):
    list_display = ("symbol", "gap_percent", "created_at")
    search_fields = ("symbol",)
    readonly_fields = [field.name for field in GapSample._meta.fields]

    def has_add_permission(self, request):
        return False
