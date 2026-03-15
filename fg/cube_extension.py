"""Cube host integration hooks discovered via Cube's extension loader."""

from __future__ import annotations

from django.urls import include, path

from fg.integration import CubeMurmurIntegration

_CUBE_INTEGRATION = CubeMurmurIntegration()

def get_i18n_urlpatterns():
    return [
        path('mumble/', include('fg.urls')),
    ]


def get_profile_panels(request):
    return _CUBE_INTEGRATION.get_profile_panels(request)
