from django.contrib import admin
from .models import Customer, Supplier, BOM, BOMItem

class BOMItemInline(admin.TabularInline):
    model = BOMItem
    extra = 0

@admin.register(BOM)
class BOMAdmin(admin.ModelAdmin):
    inlines = [BOMItemInline]

admin.site.register(Customer)
admin.site.register(Supplier)