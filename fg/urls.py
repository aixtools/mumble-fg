from django.urls import path
from . import views

app_name = 'mumble'

urlpatterns = [
    path('<int:server_id>/activate/', views.activate, name='activate'),
    path('<int:server_id>/reset-password/', views.reset_password, name='reset_password'),
    path('<int:server_id>/set-password/', views.set_password, name='set_password'),
    path('<int:server_id>/deactivate/', views.deactivate, name='deactivate'),
    path('manage/', views.mumble_manage, name='manage'),
    path('<int:mumble_user_id>/toggle-admin/', views.toggle_admin, name='toggle_admin'),
    path('<int:mumble_user_id>/sync-contract/', views.sync_contract, name='sync_contract'),
]
