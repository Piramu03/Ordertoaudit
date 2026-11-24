from django.contrib import admin
from .models import Item, StockLedger

admin.site.register(Item)


@admin.register(StockLedger)
class StockLedgerAdmin(admin.ModelAdmin):
    list_display = ("created_at", "item", "qty", "move_type", "source_type", "source_id")
    list_filter = ("move_type", "item")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False