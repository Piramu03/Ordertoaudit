from django.contrib import admin
from .models import Order, OrderItem, Invoice, InvoiceItem, Payment


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    inlines = [OrderItemInline]


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    inlines = [InvoiceItemInline]
    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Payment)