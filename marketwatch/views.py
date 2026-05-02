from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render

from .services import build_snapshot


def dashboard(request):
    return render(
        request,
        "marketwatch/dashboard.html",
        {"poll_interval": settings.PRICE_MONITOR["POLL_INTERVAL_SECONDS"]},
    )


def snapshot(request):
    return JsonResponse(build_snapshot())
