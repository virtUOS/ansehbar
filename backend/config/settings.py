# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Django settings for ansehBAR (Kontrolle der Live-Streams aus den Aufzeichnungsräumen)."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_list(name, default):
    """Comma-separated env var → list, dropping blanks.

    An empty or trailing-comma value (e.g. CORS_ALLOWED_ORIGINS unset in
    docker-compose) yields [] rather than [''], which would otherwise fail
    Django's system checks (e.g. corsheaders.E013).
    """
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def _int_or_default(name, default):
    """Env var → int; a blank or malformed value falls back to the default
    (so a typo in the AI config can't crash Django at startup)."""
    try:
        return int(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return default


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-secret-key-change-me")

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

# Refuse to start a production instance on the development key — a forgotten
# .env variable would otherwise sign sessions and CSRF tokens with a public value.
if not DEBUG and SECRET_KEY.startswith("dev-insecure"):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set to a long random value when DJANGO_DEBUG=0."
    )

ALLOWED_HOSTS = _env_list(
    "DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0,backend"
)

INSTALLED_APPS = [
    "modeltranslation",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    # Third-party
    "rest_framework",
    "corsheaders",
    "mozilla_django_oidc",
    "basicbar_auth",
    "basicbar_integrations",
    # Local apps
    "common",
    "accounts",
    "recorders",
    "opencast",
    "alarms",
]

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "corsheaders.middleware.CorsMiddleware",
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
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "ansehbar"),
        "USER": os.environ.get("POSTGRES_USER", "ansehbar"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "ansehbar"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        # Native psycopg connection pool (Django 5.1): caps concurrent
        # PostgreSQL connections under ASGI; request threads briefly wait
        # instead of failing.
        "OPTIONS": {
            "pool": {"min_size": 2, "max_size": 20, "timeout": 10},
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True

LANGUAGES = [("en", "English"), ("de", "German")]
LOCALE_PATHS = [BASE_DIR / "locale"]

# Authored-content i18n (django-modeltranslation, basicbar-Konvention):
# per-language columns for authoring fields, distinct from the UI i18n above.
MODELTRANSLATION_LANGUAGES = tuple(code for code, _ in LANGUAGES)
MODELTRANSLATION_DEFAULT_LANGUAGE = os.environ.get("CONTENT_DEFAULT_LANGUAGE", "de")
if MODELTRANSLATION_DEFAULT_LANGUAGE not in MODELTRANSLATION_LANGUAGES:
    raise ValueError(
        f"CONTENT_DEFAULT_LANGUAGE={MODELTRANSLATION_DEFAULT_LANGUAGE!r} is not one "
        f"of the supported languages {MODELTRANSLATION_LANGUAGES}."
    )
MODELTRANSLATION_FALLBACK_LANGUAGES = (
    MODELTRANSLATION_DEFAULT_LANGUAGE,
    *(c for c in MODELTRANSLATION_LANGUAGES if c != MODELTRANSLATION_DEFAULT_LANGUAGE),
)

STATIC_URL = "static/"
# Target for `collectstatic` in production (served by the reverse proxy).
STATIC_ROOT = BASE_DIR / "staticfiles"

# Uploaded media.
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# App-specific cookie names: browsers share cookies per host regardless of
# port, so other tools on the same host (e.g. several -bar tools on localhost
# in development) would overwrite "sessionid"/"csrftoken" and log each other out.
SESSION_COOKIE_NAME = "ansehbar_sessionid"
CSRF_COOKIE_NAME = "ansehbar_csrftoken"

# ansehBAR access control and monitoring (used by later tasks).
ANSEHBAR_ACCESS_GROUP = os.environ.get("ANSEHBAR_ACCESS_GROUP", "ansehbar-users")
ANSEHBAR_BOOTSTRAP_USERS = _env_list("ANSEHBAR_BOOTSTRAP_USERS", "")
ANSEHBAR_ACCESS_CONTACT = os.environ.get("ANSEHBAR_ACCESS_CONTACT", "")
MONITOR_INTERVAL_SECONDS = _int_or_default("MONITOR_INTERVAL_SECONDS", 10)
# Audio level measurement with ffmpeg (live streams during events only).
AUDIO_MONITOR_ENABLED = os.environ.get("AUDIO_MONITOR_ENABLED", "1") == "1"
# At least 1: a pool without workers or an empty sample window cannot measure.
AUDIO_MAX_PARALLEL = max(1, _int_or_default("AUDIO_MAX_PARALLEL", 4))
AUDIO_SAMPLE_SECONDS = max(1, _int_or_default("AUDIO_SAMPLE_SECONDS", 10))
# Minimum seconds between the starts of two audio passes.
AUDIO_INTERVAL_SECONDS = _int_or_default("AUDIO_INTERVAL_SECONDS", 30)
# Opencast External API (read-only). Empty URL = Opencast integration off;
# code checks bool(settings.OPENCAST_URL) at call time.
OPENCAST_URL = os.environ.get("OPENCAST_URL", "").rstrip("/")
OPENCAST_USER = os.environ.get("OPENCAST_USER", "")
OPENCAST_PASSWORD = os.environ.get("OPENCAST_PASSWORD", "")
OPENCAST_SYNC_SECONDS = _int_or_default("OPENCAST_SYNC_SECONDS", 60)
OPENCAST_LOOKAHEAD_DAYS = _int_or_default("OPENCAST_LOOKAHEAD_DAYS", 7)
OPENCAST_LOOKBACK_DAYS = _int_or_default("OPENCAST_LOOKBACK_DAYS", 7)
# Local, git-ignored site configuration (recorders, stream URL template);
# loaded with `manage.py load_site_config`.
ANSEHBAR_SITE_CONFIG = os.environ.get("ANSEHBAR_SITE_CONFIG") or str(
    BASE_DIR / "site.local.json"
)

# Console logging (container logs). The monitor logs under "recorders".
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "recorders": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# --- E-mail (stream alarms) ---
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND") or (
    "django.core.mail.backends.console.EmailBackend"
    if DEBUG
    else "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST") or "localhost"
EMAIL_PORT = _int_or_default("EMAIL_PORT", 25)
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "0") == "1"
# Seconds; a hanging SMTP server must not stall the monitor cycle for long.
EMAIL_TIMEOUT = _int_or_default("EMAIL_TIMEOUT", 10)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL") or "ansehbar@localhost"
# Language of alarm e-mails (the same for all recipients).
ALARM_LANGUAGE = os.environ.get("ALARM_LANGUAGE") or "de"

# Behind a TLS-terminating reverse proxy in production: trust its forwarded
# host/scheme so absolute URLs use https, and require secure cookies.
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Allow the React/Vite dev server to call the API during development.
CORS_ALLOWED_ORIGINS = _env_list(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:5179,http://127.0.0.1:5179",
)
# The SPA calls the API with the session cookie (same-site localhost).
CORS_ALLOW_CREDENTIALS = True
# Cross-origin POSTs from the SPA carry the CSRF token; trust its origin.
CSRF_TRUSTED_ORIGINS = _env_list(
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost:5179,http://localhost:8007",
)

REST_FRAMEWORK = {
    # Session auth only. DRF's default also enables BasicAuthentication, which
    # would expose every endpoint to password guessing against the break-glass
    # superuser (ModelBackend) — without rate limiting and bypassing CSRF.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PAGINATION_CLASS": "common.pagination.StandardPagination",
    "PAGE_SIZE": 25,
}

# Bearer token protecting /metrics (Prometheus). Empty = endpoint off (404).
METRICS_TOKEN = os.environ.get("METRICS_TOKEN", "")

# Optional AI features via a LiteLLM proxy (basicbar_integrations.ai). Off
# unless fully configured; "enabled" is derived from these, not a flag.
AI_PROVIDER = os.environ.get("AI_PROVIDER", "none")  # "none" | "litellm"
AI_BASE_URL = os.environ.get("AI_BASE_URL", "")
AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL", "")
AI_TIMEOUT = _int_or_default("AI_TIMEOUT", 30)
AI_MAX_TOKENS = _int_or_default("AI_MAX_TOKENS", 2000)
AI_DISABLE_THINKING = os.environ.get("AI_DISABLE_THINKING", "1") == "1"

# Optional machine translation for authored content
# (basicbar_integrations.translation_service). Off by default; an institution
# can self-host LibreTranslate (Apache-2.0) and point LIBRETRANSLATE_URL at it.
CONTENT_TRANSLATION_PROVIDER = os.environ.get(
    "CONTENT_TRANSLATION_PROVIDER", "none"
)  # "none" | "libretranslate"
LIBRETRANSLATE_URL = os.environ.get("LIBRETRANSLATE_URL", "")
LIBRETRANSLATE_API_KEY = os.environ.get("LIBRETRANSLATE_API_KEY", "")

# Public base URL of the SPA, used for links.
FRONTEND_BASE_URL = os.environ.get(
    "FRONTEND_BASE_URL", "http://localhost:5179"
)

# --- Authentication / OIDC (basicbar-auth) ---
# OIDC is the primary login; Django's ModelBackend stays as a local dev /
# break-glass fallback (bootstrap superuser).
AUTHENTICATION_BACKENDS = [
    "basicbar_auth.oidc.OIDCBackend",
    "django.contrib.auth.backends.ModelBackend",
]

OIDC_RP_CLIENT_ID = os.environ.get("OIDC_RP_CLIENT_ID", "")
OIDC_RP_CLIENT_SECRET = os.environ.get("OIDC_RP_CLIENT_SECRET", "")
OIDC_RP_SIGN_ALGO = "RS256"
# Keep the ID token in the session so logout can send it as id_token_hint.
OIDC_STORE_ID_TOKEN = True

# Endpoints: set them explicitly, or set OIDC_OP_ISSUER to derive them from the
# provider's discovery document. Explicit values always win (needed for the
# local browser/backchannel split). Switching provider = change these env vars.
OIDC_OP_ISSUER = os.environ.get("OIDC_OP_ISSUER", "")
OIDC_OP_AUTHORIZATION_ENDPOINT = os.environ.get("OIDC_OP_AUTHORIZATION_ENDPOINT", "")
OIDC_OP_TOKEN_ENDPOINT = os.environ.get("OIDC_OP_TOKEN_ENDPOINT", "")
OIDC_OP_USER_ENDPOINT = os.environ.get("OIDC_OP_USER_ENDPOINT", "")
OIDC_OP_JWKS_ENDPOINT = os.environ.get("OIDC_OP_JWKS_ENDPOINT", "")
OIDC_OP_LOGOUT_ENDPOINT = os.environ.get("OIDC_OP_LOGOUT_ENDPOINT", "")

if OIDC_OP_ISSUER and not OIDC_OP_AUTHORIZATION_ENDPOINT:
    from basicbar_auth.discovery import discover_endpoints

    _discovered = discover_endpoints(OIDC_OP_ISSUER)
    OIDC_OP_AUTHORIZATION_ENDPOINT = _discovered.get("authorization_endpoint", "")
    OIDC_OP_TOKEN_ENDPOINT = OIDC_OP_TOKEN_ENDPOINT or _discovered.get("token_endpoint", "")
    OIDC_OP_USER_ENDPOINT = OIDC_OP_USER_ENDPOINT or _discovered.get("userinfo_endpoint", "")
    OIDC_OP_JWKS_ENDPOINT = OIDC_OP_JWKS_ENDPOINT or _discovered.get("jwks_uri", "")
    OIDC_OP_LOGOUT_ENDPOINT = OIDC_OP_LOGOUT_ENDPOINT or _discovered.get("end_session_endpoint", "")

# Fail fast in production: with an issuer configured but no endpoints (the
# discovery document was unreachable or incomplete — see the WARNING from
# basicbar_auth.discovery), every login would otherwise fail later with an
# opaque error. In DEBUG the dev stack may simply not have Keycloak up yet.
if OIDC_OP_ISSUER and not DEBUG and not (OIDC_OP_AUTHORIZATION_ENDPOINT and OIDC_OP_TOKEN_ENDPOINT):
    raise ImproperlyConfigured(
        f"OIDC_OP_ISSUER={OIDC_OP_ISSUER!r} is set, but the OIDC endpoints could not be "
        "resolved — the provider's discovery document was unreachable. Set the "
        "OIDC_OP_*_ENDPOINT variables explicitly or fix the issuer URL."
    )

OIDC_OP_LOGOUT_URL_METHOD = "basicbar_auth.oidc.provider_logout_url"

# Claim mapping (provider-agnostic; defaults are standard OIDC claim names).
OIDC_CLAIM_USERNAME = os.environ.get("OIDC_CLAIM_USERNAME", "preferred_username")
OIDC_CLAIM_EMAIL = os.environ.get("OIDC_CLAIM_EMAIL", "email")
OIDC_CLAIM_FIRST_NAME = os.environ.get("OIDC_CLAIM_FIRST_NAME", "given_name")
OIDC_CLAIM_LAST_NAME = os.environ.get("OIDC_CLAIM_LAST_NAME", "family_name")
# Group/role claim, and the group that grants Django admin (empty = disabled,
# admins then managed manually via Django admin / a createsuperuser account).
OIDC_GROUPS_CLAIM = os.environ.get("OIDC_GROUPS_CLAIM", "groups")
OIDC_ADMIN_GROUP = os.environ.get("OIDC_ADMIN_GROUP", "")
# Opt-in: heal re-issued IdP subjects (re-imported dev realm, realm migration)
# by matching on the username. Enable ONLY when the IdP never re-assigns
# usernames to different people — see basicbar-auth's operator notes.
OIDC_MATCH_BY_USERNAME_FALLBACK = (
    os.environ.get("OIDC_MATCH_BY_USERNAME_FALLBACK", "0") == "1"
)

# Where to send the browser after login/logout (the SPA).
LOGIN_REDIRECT_URL = os.environ.get(
    "OIDC_LOGIN_REDIRECT_URL", "http://localhost:5179/"
)
LOGOUT_REDIRECT_URL = os.environ.get(
    "OIDC_LOGOUT_REDIRECT_URL", "http://localhost:5179/"
)
# On a failed/declined login (incl. a silent prompt=none attempt with no IdP
# session) send the browser back to the SPA with a marker, so the landing page
# shows instead of erroring and does not retry the silent login.
LOGIN_REDIRECT_URL_FAILURE = LOGIN_REDIRECT_URL.rstrip("/") + "/?sso=failed"
