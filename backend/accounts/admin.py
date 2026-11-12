from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Approval, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin[User]):
    ordering = ("name",)
    list_display = ("name", "email", "role", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("name", "email")
    filter_horizontal = ("locations",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Pessoa", {"fields": ("name", "role", "locations")}),
        ("Acesso", {"fields": ("is_active", "is_staff", "is_superuser")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "name", "role", "password1", "password2")}),)


@admin.register(Approval)
class ApprovalAdmin(admin.ModelAdmin[Approval]):
    list_display = ("created_at", "action", "approver", "requested_by", "location", "consumed_at")
    list_filter = ("action",)

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        return False
