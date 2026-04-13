from __future__ import annotations

from django.urls import path

from .views import (
    status_ice_users_json,
    status_mains_json,
    status_mains_with_alts_json,
    status_orphans_json,
    status_pilot_wealth_json,
    status_pilots_json,
    status_spies_json,
    status_view,
)

app_name = "monitor"

urlpatterns = [
    path("monitor/status/", status_view, name="status"),
    path(
        "monitor/status/mains/",
        status_mains_json,
        name="status-mains",
    ),
    path(
        "monitor/status/mains-with-alts/",
        status_mains_with_alts_json,
        name="status-mains-with-alts",
    ),
    path(
        "monitor/status/orphans/",
        status_orphans_json,
        name="status-orphans",
    ),
    path(
        "monitor/status/pilots/",
        status_pilots_json,
        name="status-pilots",
    ),
    path(
        "monitor/status/spies/",
        status_spies_json,
        name="status-spies",
    ),
    path(
        "monitor/status/pilot-wealth/",
        status_pilot_wealth_json,
        name="status-pilot-wealth",
    ),
    path(
        "monitor/status/ice-users/",
        status_ice_users_json,
        name="status-ice-users",
    ),
]
