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
    path('controls/', views.mumble_controls, name='controls'),
    path('acl/', views.acl_list, name='acl_list'),
    path('acl/search/', views.acl_search, name='acl_search'),
    path('acl/batch-create/', views.acl_batch_create, name='acl_batch_create'),
    path('acl/eligible/', views.acl_eligible, name='acl_eligible'),
    path('acl/blocked/', views.acl_blocked, name='acl_blocked'),
    path('acl/sync/', views.acl_sync, name='acl_sync'),
    path('acl/<int:rule_id>/toggle-deny/', views.acl_toggle_deny, name='acl_toggle_deny'),
    path('acl/<int:rule_id>/toggle-admin/', views.acl_toggle_admin, name='acl_toggle_admin'),
    path('acl/<int:rule_id>/delete/', views.acl_delete, name='acl_delete'),
    path('group-mapping/', views.group_mapping, name='group_mapping'),
    path('group-mapping/refresh/', views.group_mapping_refresh, name='group_mapping_refresh'),
    path('group-mapping/add/', views.group_mapping_add, name='group_mapping_add'),
    path('group-mapping/remove/', views.group_mapping_remove, name='group_mapping_remove'),
    path('group-mapping/toggle-cube-ignore/', views.group_mapping_toggle_cube_ignore, name='group_mapping_toggle_cube_ignore'),
    path('group-mapping/toggle-murmur-ignore/', views.group_mapping_toggle_murmur_ignore, name='group_mapping_toggle_murmur_ignore'),
    path('group-mapping/cleanup-ignored/', views.group_mapping_cleanup_ignored, name='group_mapping_cleanup_ignored'),
    path('links/', views.temp_links, name='temp_links'),
    path('links/create/', views.temp_link_create, name='temp_link_create'),
    path('links/<int:link_id>/toggle-active/', views.temp_link_toggle_active, name='temp_link_toggle_active'),
    path('links/<int:link_id>/delete/', views.temp_link_delete, name='temp_link_delete'),
    path('temp/<slug:token>/', views.temp_link_public, name='temp_link_public'),
]
