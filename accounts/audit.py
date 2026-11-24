from .models import AuditLog


def log(user, action, obj, detail=""):
    """Record who did what, to which record, and when."""
    AuditLog.objects.create(
        user=user, action=action, object_type=obj.__class__.__name__,
        object_id=obj.pk, detail=detail,
    )