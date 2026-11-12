"""
Arara settings. Everything that varies between environments comes from the environment
(see .env.example); production refuses to boot with development defaults.
"""

from pathlib import Path

import django_stubs_ext
import environ
from django.core.exceptions import ImproperlyConfigured

# Lets annotations like `ModelAdmin[Location]` work at runtime, not only for the type checker.
# DRF's classes are patched in CommonConfig.ready(): importing DRF here would make it read its
# settings before REST_FRAMEWORK below exists, and it would keep that empty read.
django_stubs_ext.monkeypatch()

BASE_DIR = Path(__file__).resolve().parent.parent

DEV_SECRET_KEY = "dev-only-insecure-secret-key-change-me"  # refused in production below

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

ENVIRONMENT = env.str("ENVIRONMENT", default="development")  # development | test | production
PRODUCTION = ENVIRONMENT == "production"
DEBUG = env.bool("DEBUG", default=not PRODUCTION)

SECRET_KEY = env.str("SECRET_KEY", default=DEV_SECRET_KEY)
if PRODUCTION and (SECRET_KEY == DEV_SECRET_KEY or len(SECRET_KEY) < 50):
    raise ImproperlyConfigured("SECRET_KEY: set a random value of 50+ characters in production")
if PRODUCTION and DEBUG:
    raise ImproperlyConfigured("DEBUG must be off in production")

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# Browser origin of the web app. The SPA reaches the API through a same-origin `/api` rewrite,
# so the session cookie stays first-party; this origin is trusted for CSRF.
WEB_ORIGIN = env.str("WEB_ORIGIN", default="http://localhost:5174").rstrip("/")
CSRF_TRUSTED_ORIGINS = [WEB_ORIGIN]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "common",
    "locations",
    "accounts",
    "audit",
    "catalog",
    "stock",
    "purchasing",
    "transfers",
    "counts",
    "pos",
]

# A cashier may give up to this discount on a sale on their own; above it, a manager approves.
POS_CASHIER_MAX_DISCOUNT_PERCENT = env.int("POS_CASHIER_MAX_DISCOUNT_PERCENT", default=10)

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# In production WhiteNoise serves the admin's collected static files; in development Django does.
if PRODUCTION:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://arara:arara@localhost:5436/arara"),
}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# The interface is Brazilian Portuguese; the store's wall clock is São Paulo time.
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Sessions and CSRF for a same-origin SPA. In production the cookies get the __Host- prefix:
# Secure, Path=/ and no Domain, so a sibling subdomain can't set or read them.
SESSION_COOKIE_AGE = 12 * 60 * 60
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # the SPA reads it and echoes it in X-CSRFToken
CSRF_COOKIE_SAMESITE = "Lax"
if PRODUCTION:
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_NAME = "__Host-sessionid"
    CSRF_COOKIE_NAME = "__Host-csrftoken"
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    # HTTPS is enforced at the edge (Render and Vercel redirect, and Vercel sends HSTS for its
    # domain). Redirecting inside Django would also redirect the platform's plain-HTTP health check.
    SILENCED_SYSTEM_CHECKS = ["security.W004", "security.W008"]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Money travels as strings ("129.90"): never as a float the client could round.
    "COERCE_DECIMAL_TO_STRING": True,
    "EXCEPTION_HANDLER": "common.errors.api_exception_handler",
    # Endpoints that check a password (sign-in, manager approvals) are rate limited per client.
    "DEFAULT_THROTTLE_RATES": {"credentials": env.str("CREDENTIALS_RATE", default="10/min")},
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Arara API",
    "DESCRIPTION": "Inventory, purchasing and point of sale for clothing stores.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Public on purpose: the API documentation is part of the portfolio. Every endpoint it
    # describes still requires a session.
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env.str("LOG_LEVEL", default="INFO")},
}
