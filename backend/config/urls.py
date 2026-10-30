# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Root URL configuration."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from accounts.views import whoami

urlpatterns = [
    path("admin/", admin.site.urls),
    # OIDC login/logout/silent/back-channel/callback and api/whoami/language/.
    path("", include("basicbar_auth.urls")),
    path("api/whoami/", whoami),
]

# Serve uploaded media and static files during local development. (Static
# needs explicit wiring because we run uvicorn, not `manage.py runserver`.)
if settings.DEBUG:
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
