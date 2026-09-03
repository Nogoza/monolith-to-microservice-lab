from django.http import JsonResponse


def health(request):
    """Liveness endpoint used by the load balancer / orchestrator."""
    return JsonResponse({"status": "ok"})
