from django.contrib import admin

from .models import Location


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin[Location]):
    list_display = ("code", "name", "kind", "is_active")
    list_filter = ("kind", "is_active")
