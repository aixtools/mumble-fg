from django.utils.translation import gettext_lazy as _


def _can_view_mumble_controls(request):
    if not request.user.is_authenticated:
        return False
    return (
        request.user.is_superuser
        or request.user.has_perm('mumble_fg.view_accessrule')
        or request.user.has_perm('mumble_fg.view_group_mapping')
        or request.user.has_perm('mumble_fg.view_temp_links')
    )

def _can_view_acl(request):
    if not request.user.is_authenticated:
        return False
    return request.user.is_superuser or request.user.has_perm('mumble_fg.view_accessrule')


def _can_manage_mumble(request):
    if not request.user.is_authenticated:
        return False
    return (
        request.user.is_superuser
        or request.user.has_perm('mumble.manage_mumble_admin')
        or request.user.has_perm('mumble_fg.manage_mumble_admin')
    )


SIDEBAR_ITEMS = [
    {
        'key': 'mumble_controls',
        'parent_key': 'alliance',
        'label': _('Mumble Controls'),
        'url_name': 'mumble:controls',
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
        'active_paths': ['mumble-ui/controls', 'mumble-ui/acl', 'mumble-ui/group-mapping', 'mumble-ui/links'],
        'requires_auth': True,
        'requires_member': True,
        'visible': _can_view_mumble_controls,
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
