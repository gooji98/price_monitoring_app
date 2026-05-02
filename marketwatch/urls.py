from django.urls import path

from . import views


app_name = "marketwatch"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("api/snapshot/", views.snapshot, name="snapshot"),
]
