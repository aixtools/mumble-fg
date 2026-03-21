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
    from celery.schedules import crontab

    return {
        'mumble_fg.periodic_acl_sync': {
            'task': 'fg.tasks.periodic_acl_sync',
            'schedule': crontab(minute='*/10'),
        },
        'mumble_fg.periodic_group_sync': {
            'task': 'fg.tasks.update_all_mumble_groups',
            'schedule': crontab(minute=0),
        },
    }
