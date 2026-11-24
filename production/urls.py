from django.urls import path

from . import views

app_name = "production"

urlpatterns = [
    path("purchases/new/", views.purchase_new, name="purchase_new"),
    path("runs/", views.run_list, name="run_list"),
    path("runs/new/", views.run_new, name="run_new"),
    path("runs/<int:pk>/", views.run_detail, name="run_detail"),
    path("runs/<int:pk>/costs/", views.run_costs, name="run_costs"),
    path("runs/<int:pk>/reverse/", views.run_reverse, name="run_reverse"),
]