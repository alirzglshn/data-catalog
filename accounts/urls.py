"""authentication endpoints

no custom views are needed here, simplejwt's built in views already
implement the obtain/refresh flow correctly, wrapping them ourselves
would only add code without adding behaviour
"""

from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

app_name = "accounts"

urlpatterns = [
    path("token/", TokenObtainPairView.as_view(), name="token-obtain"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
]
