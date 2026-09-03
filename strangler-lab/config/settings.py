"""
Django settings for the storefront project.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- core -------------------------------------------------------------
SECRET_KEY = "django-insecure-8f2k4jz9q!x3m0t7v-storefront-prod-key-do-not-share"

DEBUG = True

ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "catalog",
    "cart",
    "orders",
    "payments",
    "reports",
    "accounts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- database -----------------------------------------------------------
# Points at the "db" service in docker-compose.yml.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "storefront",
        "USER": "storefront",
        "PASSWORD": "storefront_pw",
        "HOST": "db",
        "PORT": "5432",
    }
}

# --- auth -----------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "catalog:home"
LOGOUT_REDIRECT_URL = "catalog:home"

# --- sessions -----------------------------------------------------------
# Cache-backed sessions, fast and simple - no extra moving parts to run.
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "storefront-cache",
    }
}

# --- i18n -----------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- static & media -----------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- storefront-specific paths -----------------------------------------------------------
LOG_DIR = BASE_DIR / "logs"
ORDERS_LOG_FILE = LOG_DIR / "orders.log"
SCHEDULER_LOG_FILE = LOG_DIR / "scheduler.log"

# Minutes a cart reservation is held before the cleanup job releases the stock.
CART_RESERVATION_TIMEOUT_MINUTES = 30
