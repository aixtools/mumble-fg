from django.utils.translation import gettext_lazy as _

from .host import get_host_adapter


def _can_view_acl(request):
    if not request.user.is_authenticated:
        return False
    return (
        request.user.is_staff
        or get_host_adapter().user_is_alliance_leader(request.user)
        or request.user.has_perm('mumble_fg.view_accessrule')
    )


def _can_manage_mumble(request):
    if not request.user.is_authenticated:
        return False
    return (
        request.user.is_staff
        or get_host_adapter().user_is_alliance_leader(request.user)
        or request.user.has_perm('mumble.manage_mumble_admin')
    )


SIDEBAR_ITEMS = [
    {
        'key': 'mumble_acl',
        'parent_key': 'alliance',
        'label': _('Mumble ACL'),
        'url_name': 'mumble:acl_list',
        'icon_svg': (
            '<svg class="sidebar-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="2">'
            '<rect x="4" y="5" width="16" height="14" rx="2"></rect>'
            '<line x1="8" y1="9" x2="16" y2="9"></line>'
            '<line x1="8" y1="13" x2="16" y2="13"></line>'
            '<line x1="8" y1="17" x2="12" y2="17"></line>'
            '</svg>'
        ),
        'priority': 56,
        'active_paths': ['mumble-ui/acl'],
        'requires_auth': True,
        'requires_member': True,
        'visible': _can_view_acl,
    },
    {
        'key': 'mumble_manage',
        'parent_key': 'alliance',
        'label': _('Murmur Admins'),
        'url_name': 'mumble:manage',
        'icon_svg': (
            '<svg class="sidebar-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="2">'
            '<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>'
            '<path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>'
            '<line x1="12" y1="19" x2="12" y2="23"></line>'
            '<line x1="8" y1="23" x2="16" y2="23"></line>'
            '</svg>'
        ),
        'priority': 57,
        'active_paths': ['mumble-ui/manage'],
        'requires_auth': True,
        'requires_member': True,
        'visible': _can_manage_mumble,
    },
]
