from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render

from orders.models import Order

from .forms import ProfileForm, RegistrationForm


class StorefrontLoginView(LoginView):
    template_name = "accounts/login.html"


def logout_view(request):
    auth_logout(request)
    return redirect("catalog:home")


def register(request):
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            return redirect("catalog:home")
    else:
        form = RegistrationForm()
    return render(request, "accounts/register.html", {"form": form})


@login_required
def profile(request):
    profile_obj = request.user.profile
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=profile_obj)
        if form.is_valid():
            form.save()
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=profile_obj)

    recent_orders = Order.objects.filter(user=request.user).order_by("-created_at")[:10]

    return render(request, "accounts/profile.html", {"form": form, "recent_orders": recent_orders})
