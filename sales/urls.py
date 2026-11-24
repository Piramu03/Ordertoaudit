from django.urls import path

from . import views

app_name = "sales"

urlpatterns = [
    path("orders/new/", views.new_order, name="new_order"),
    path("orders/mine/", views.my_orders, name="my_orders"),
    path("orders/", views.admin_orders, name="admin_orders"),
    path("orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("invoices/", views.invoice_list, name="invoice_list"),
    path("invoices/<int:pk>/", views.invoice_detail, name="invoice_detail"),
    path("invoices/<int:pk>/pdf/", views.invoice_pdf, name="invoice_pdf"),
    path("share/<str:token>/", views.invoice_shared_pdf, name="invoice_shared_pdf"),
]