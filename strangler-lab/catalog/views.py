from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

from .models import Category, Product


def home(request):
    categories = Category.objects.all()[:12]
    featured = Product.objects.select_related("category").order_by("-created_at")[:12]
    return render(request, "catalog/home.html", {"categories": categories, "featured": featured})


def product_list(request):
    products = Product.objects.select_related("category").all()

    category_slug = request.GET.get("category")
    category = None
    if category_slug:
        category = get_object_or_404(Category, slug=category_slug)
        products = products.filter(category=category)

    query = request.GET.get("q")
    if query:
        products = products.filter(name__icontains=query)

    paginator = Paginator(products, 24)
    page_obj = paginator.get_page(request.GET.get("page"))

    categories = Category.objects.all()

    return render(
        request,
        "catalog/product_list.html",
        {
            "page_obj": page_obj,
            "categories": categories,
            "current_category": category,
            "query": query or "",
        },
    )


def product_detail(request, slug):
    product = get_object_or_404(Product.objects.select_related("category"), slug=slug)
    related = (
        Product.objects.filter(category=product.category)
        .exclude(id=product.id)
        .order_by("-created_at")[:6]
    )
    return render(request, "catalog/product_detail.html", {"product": product, "related": related})
