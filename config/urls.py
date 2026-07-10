from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

# everything under /api/v1/ is versioned so future breaking changes
# (a v2 response shape, for example) can be added alongside this one
# instead of replacing it outright
v1_patterns = [
    path("auth/", include("accounts.urls")),
    path("catalog/", include("catalog.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(v1_patterns)),
]


if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
