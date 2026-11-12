from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    """
    Who did something sensitive, where and when: price changes, approved discounts, stock
    adjustments, cash differences. Append-only; the data field holds what was decided.
    """

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    action = models.CharField(max_length=60)
    location = models.ForeignKey(
        "locations.Location", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    target_type = models.CharField(max_length=40, blank=True)
    target_id = models.CharField(max_length=40, blank=True)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-at",)
        indexes = (models.Index(fields=("action", "-at")),)

    def __str__(self) -> str:
        return f"{self.at:%Y-%m-%d %H:%M} {self.action} by {self.actor_id}"
