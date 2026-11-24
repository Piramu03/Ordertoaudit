from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .models import AuditLog
from .permissions import role_required


@login_required
def home(request):
    role = request.user.role
    if role == "salesman":
        return redirect("sales:new_order")
    if role == "admin":
        return redirect("sales:admin_orders")
    if role == "production":
        return redirect("production:run_list")
    if role == "owner":
        return redirect("reports:dashboard")
    return render(request, "home.html")


@role_required("admin", "auditor", "owner")
def audit_log(request):
    action = request.GET.get("action", "")
    logs = AuditLog.objects.select_related("user")
    if action:
        logs = logs.filter(action=action)
    actions = AuditLog.objects.order_by("action").values_list("action", flat=True).distinct()
    return render(request, "accounts/audit_log.html", {
        "logs": logs[:200], "actions": actions, "action": action,
    })