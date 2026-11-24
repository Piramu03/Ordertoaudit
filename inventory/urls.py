from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.stock_summary, name="summary"),
    path("<int:pk>/", views.stock_ledger, name="ledger"),
]