"""Cube host integration hooks discovered via Cube's extension loader."""

from __future__ import annotations

from django.urls import include, path

from fg.integration import CubeMurmurIntegration

_CUBE_INTEGRATION = CubeMurmurIntegration()

def get_i18n_urlpatterns():
    return [
        path('mumble-ui/', include('fg.urls')),
    ]


def get_profile_panels(request):
    return _CUBE_INTEGRATION.get_profile_panels(request)


def get_periodic_tasks():
    try:
        from celery.schedules import crontab
    except ImportError:
        # Mock hosts such as mockcube may not install Celery. Keep the extension
        # discoverable anyway so host-context tests can exercise the FG package.
        def crontab(**kwargs):
            return {'type': 'crontab', **kwargs}

    return {
        'mumble_fg.periodic_acl_sync': {
            'task': 'fg.tasks.periodic_acl_sync',
            'schedule': crontab(minute='*/10'),
        },
    }
