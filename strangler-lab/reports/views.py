from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from . import services


@login_required
def sales(request):
    report = services.build_sales_report()
    return render(request, "reports/sales.html", {"report": report})
