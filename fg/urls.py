from django.urls import path
from . import views

app_name = 'mumble'

urlpatterns = [
    path('<int:server_id>/activate/', views.activate, name='activate'),
    path('<int:server_id>/reset-password/', views.reset_password, name='reset_password'),
    path('<int:server_id>/set-password/', views.set_password, name='set_password'),
    path('profile/reset-password/', views.profile_reset_password, name='profile_reset_password'),
    path('profile/set-password/', views.profile_set_password, name='profile_set_password'),
    path('<int:server_id>/deactivate/', views.deactivate, name='deactivate'),
    path('manage/', views.mumble_manage, name='manage'),
    path('<int:mumble_user_id>/toggle-admin/', views.toggle_admin, name='toggle_admin'),
    path(
        'pilots/<int:pkid>/servers/<int:server_id>/toggle-admin/',
        views.toggle_admin_registration,
        name='toggle_admin_registration',
    ),
    path('<int:mumble_user_id>/sync-contract/', views.sync_contract, name='sync_contract'),
    path(
        'pilots/<int:pkid>/servers/<int:server_id>/sync-contract/',
        views.sync_contract_registration,
        name='sync_contract_registration',
    ),
    path('acl/', views.acl_list, name='acl_list'),
    path('acl/search/', views.acl_search, name='acl_search'),
    path('acl/batch-create/', views.acl_batch_create, name='acl_batch_create'),
    path('acl/eligible/', views.acl_eligible, name='acl_eligible'),
    path('acl/blocked/', views.acl_blocked, name='acl_blocked'),
    path('acl/sync/', views.acl_sync, name='acl_sync'),
    path('acl/<int:rule_id>/toggle-deny/', views.acl_toggle_deny, name='acl_toggle_deny'),
    path('acl/<int:rule_id>/toggle-admin/', views.acl_toggle_admin, name='acl_toggle_admin'),
    path('acl/<int:rule_id>/delete/', views.acl_delete, name='acl_delete'),
]
