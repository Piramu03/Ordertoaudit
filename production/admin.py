from django.contrib import admin
from .models import Purchase, ProductionRun, ProductionRunItem


class RunItemInline(admin.TabularInline):
    model = ProductionRunItem
    extra = 0


@admin.register(ProductionRun)
class ProductionRunAdmin(admin.ModelAdmin):
    inlines = [RunItemInline]

admin.site.register(Purchase)