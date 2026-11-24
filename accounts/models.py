from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings


class User(AbstractUser):
    class Role(models.TextChoices):
        SALESMAN = "salesman", "Salesman"
        ADMIN = "admin", "Factory Admin"
        PRODUCTION = "production", "Production Supervisor"
        AUDITOR = "auditor", "Auditor"
        OWNER = "owner", "Owner"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.ADMIN)

# Create your models here.
class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=40)
    object_type = models.CharField(max_length=30)
    object_id = models.PositiveIntegerField()
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.created_at:%d %b %H:%M} {self.user} {self.action}"