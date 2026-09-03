"""
Seeds a full demo dataset: users, categories, products (with placeholder
images), historical orders, order items and payments.

Idempotent - safe to re-run. Each stage checks whether it has already hit
its target row count and skips straight past if so.
"""

import io
import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from faker import Faker

from accounts.models import Profile
from catalog.models import Category, Product
from orders.models import Order, OrderItem
from payments.models import Payment

USER_COUNT = 20_000
CATEGORY_COUNT = 200
PRODUCT_COUNT = 50_000
ORDER_COUNT = 200_000
ORDER_MONTHS_SPAN = 24

ORDER_STATUS_WEIGHTS = [
    ("pending", 5),
    ("paid", 10),
    ("shipped", 15),
    ("delivered", 55),
    ("cancelled", 10),
    ("refunded", 5),
]
STATUS_CHOICES_LIST = [s for s, _ in ORDER_STATUS_WEIGHTS]
STATUS_WEIGHTS_LIST = [w for _, w in ORDER_STATUS_WEIGHTS]

PAYMENT_STATUS_BY_ORDER_STATUS = {
    "pending": "pending",
    "paid": "approved",
    "shipped": "approved",
    "delivered": "approved",
    "cancelled": "declined",
    "refunded": "refunded",
}

DEFAULT_PASSWORD_HASH = make_password("password123")

fake = Faker()

PLACEHOLDER_COLORS = [
    (211, 84, 0), (41, 128, 185), (39, 174, 96), (142, 68, 173),
    (243, 156, 18), (192, 57, 43), (22, 160, 133), (44, 62, 80),
    (127, 140, 141), (211, 84, 133),
]


def _build_placeholder_images():
    """Render a handful of solid-color placeholder PNGs once, in memory."""
    from PIL import Image

    images = []
    for color in PLACEHOLDER_COLORS:
        buf = io.BytesIO()
        Image.new("RGB", (300, 300), color).save(buf, format="PNG")
        images.append(buf.getvalue())
    return images


class Command(BaseCommand):
    help = "Seed the storefront with demo users, products, orders and payments."

    def handle(self, *args, **options):
        started = timezone.now()

        self.seed_users()
        categories = self.seed_categories()
        products = self.seed_products(categories)
        self.repair_missing_media()
        self.seed_orders(products)

        elapsed = (timezone.now() - started).total_seconds()
        self.stdout.write(self.style.SUCCESS(f"Done in {elapsed:.1f}s"))

    # -- users -----------------------------------------------------------

    def seed_users(self):
        existing = User.objects.count()
        if existing >= USER_COUNT:
            self.stdout.write(f"Users already seeded ({existing}), skipping.")
            return

        self.stdout.write(f"Seeding {USER_COUNT} users...")
        to_create = USER_COUNT - existing
        batch = []
        batch_size = 2000

        for i in range(existing, existing + to_create):
            first_name = fake.first_name()
            last_name = fake.last_name()
            batch.append(
                User(
                    username=f"user{i}",
                    email=f"user{i}@example.test",
                    first_name=first_name,
                    last_name=last_name,
                    password=DEFAULT_PASSWORD_HASH,
                    is_active=True,
                )
            )
            if len(batch) >= batch_size:
                created = User.objects.bulk_create(batch)
                Profile.objects.bulk_create([Profile(user=u) for u in created])
                batch = []

        if batch:
            created = User.objects.bulk_create(batch)
            Profile.objects.bulk_create([Profile(user=u) for u in created])

        User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@example.test",
                "is_staff": True,
                "is_superuser": True,
                "password": DEFAULT_PASSWORD_HASH,
            },
        )

        self.stdout.write(self.style.SUCCESS("Users seeded."))

    # -- categories -----------------------------------------------------------

    def seed_categories(self):
        existing = list(Category.objects.all())
        if len(existing) >= CATEGORY_COUNT:
            self.stdout.write(f"Categories already seeded ({len(existing)}), skipping.")
            return existing

        self.stdout.write(f"Seeding {CATEGORY_COUNT} categories...")
        needed = CATEGORY_COUNT - len(existing)
        used_slugs = {c.slug for c in existing}
        batch = []
        n = 0
        while n < needed:
            name = f"{fake.word().title()} {fake.word().title()}"
            slug = slugify(name)
            if slug in used_slugs:
                continue
            used_slugs.add(slug)
            batch.append(Category(name=name, slug=slug))
            n += 1

        Category.objects.bulk_create(batch)
        self.stdout.write(self.style.SUCCESS("Categories seeded."))
        return list(Category.objects.all())

    # -- products -----------------------------------------------------------

    def seed_products(self, categories):
        existing = Product.objects.count()
        if existing >= PRODUCT_COUNT:
            self.stdout.write(f"Products already seeded ({existing}), skipping.")
            return list(Product.objects.values_list("id", "price"))

        self.stdout.write(f"Seeding {PRODUCT_COUNT} products...")
        placeholder_images = _build_placeholder_images()
        to_create = PRODUCT_COUNT - existing
        batch = []
        batch_size = 2000

        for i in range(existing, existing + to_create):
            category = random.choice(categories)
            name = f"{fake.word().title()} {fake.word().title()} {i}"
            slug = f"product-{i}"
            price = Decimal(random.randint(500, 50000)) / Decimal("100")
            stock = random.randint(0, 500)

            product = Product(
                category=category,
                name=name,
                slug=slug,
                description=fake.paragraph(nb_sentences=3),
                price=price,
                stock=stock,
                reserved_stock=0,
            )
            image_bytes = placeholder_images[i % len(placeholder_images)]
            product.image.save(f"product-{i}.png", ContentFile(image_bytes), save=False)

            batch.append(product)
            if len(batch) >= batch_size:
                Product.objects.bulk_create(batch)
                batch = []

        if batch:
            Product.objects.bulk_create(batch)

        self.stdout.write(self.style.SUCCESS("Products seeded."))
        return list(Product.objects.values_list("id", "price"))

    # -- media repair -----------------------------------------------------------

    def repair_missing_media(self):
        """
        MEDIA_ROOT isn't persisted across container recreation (see
        catalog.models.Product.image / MEDIA_ROOT). That means a
        product row can end up pointing at an image path that no
        longer has a file behind it, independent of whether the product
        *rows* still satisfy the row-count idempotency check in
        seed_products(). This repairs just the missing files - it never
        touches a database row, only rewrites bytes at paths the DB
        already references.
        """
        products = list(Product.objects.exclude(image="").only("id", "image"))
        missing = [p for p in products if not default_storage.exists(p.image.name)]

        if not missing:
            self.stdout.write("All product image files present, nothing to repair.")
            return

        self.stdout.write(f"Repairing {len(missing)} missing product image file(s)...")
        placeholder_images = _build_placeholder_images()

        for product in missing:
            image_bytes = placeholder_images[product.id % len(placeholder_images)]
            default_storage.save(product.image.name, ContentFile(image_bytes))

        self.stdout.write(self.style.SUCCESS(f"Repaired {len(missing)} image file(s); no rows changed."))

    # -- orders / order items / payments -----------------------------------------------------------

    def seed_orders(self, products):
        existing = Order.objects.count()
        if existing >= ORDER_COUNT:
            self.stdout.write(f"Orders already seeded ({existing}), skipping.")
            return

        self.stdout.write(f"Seeding {ORDER_COUNT} orders...")
        to_create = ORDER_COUNT - existing

        user_ids = list(User.objects.exclude(username="admin").values_list("id", flat=True))
        now = timezone.now()
        span_seconds = ORDER_MONTHS_SPAN * 30 * 24 * 3600

        batch_size = 2000
        created_count = 0

        while created_count < to_create:
            n = min(batch_size, to_create - created_count)
            order_objs = []
            order_items_plan = []  # list of list[(product_id, price, qty)]

            for _ in range(n):
                offset_seconds = random.randint(0, span_seconds)
                created_at = now - timedelta(seconds=offset_seconds)
                status = random.choices(STATUS_CHOICES_LIST, weights=STATUS_WEIGHTS_LIST, k=1)[0]

                num_items = random.randint(1, 5)
                chosen = random.sample(products, min(num_items, len(products)))
                items_plan = []
                total = Decimal("0")
                for product_id, price in chosen:
                    qty = random.randint(1, 3)
                    items_plan.append((product_id, price, qty))
                    total += price * qty

                order_items_plan.append(items_plan)
                order_objs.append(
                    Order(
                        user_id=random.choice(user_ids),
                        status=status,
                        total=total,
                        shipping_address=fake.address().replace("\n", ", "),
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )

            with transaction.atomic():
                created_orders = Order.objects.bulk_create(order_objs)

                item_objs = []
                payment_objs = []
                for order, items_plan in zip(created_orders, order_items_plan):
                    for product_id, price, qty in items_plan:
                        item_objs.append(
                            OrderItem(order=order, product_id=product_id, quantity=qty, unit_price=price)
                        )
                    payment_objs.append(
                        Payment(
                            order=order,
                            amount=order.total,
                            method=random.choice(["card", "paypal"]),
                            status=PAYMENT_STATUS_BY_ORDER_STATUS[order.status],
                            transaction_ref=f"txn_seed_{order.id}",
                            created_at=order.created_at,
                        )
                    )

                OrderItem.objects.bulk_create(item_objs)
                Payment.objects.bulk_create(payment_objs)

            created_count += n
            self.stdout.write(f"  ...{created_count}/{to_create} orders")

        self.stdout.write(self.style.SUCCESS("Orders, order items and payments seeded."))
