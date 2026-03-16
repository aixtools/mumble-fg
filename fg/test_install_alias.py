import sys
from pathlib import Path

from django.test import SimpleTestCase

from fg.cube_extension import get_i18n_urlpatterns, get_periodic_tasks

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mumble_ui.apps import MumbleUiConfig


class InstallAliasTest(SimpleTestCase):
    def test_mumble_ui_config_points_to_fg_app(self):
        self.assertEqual(MumbleUiConfig.name, 'fg')
        self.assertEqual(MumbleUiConfig.label, 'mumble_fg')

    def test_cube_extension_mounts_under_mumble_ui(self):
        patterns = get_i18n_urlpatterns()

        self.assertEqual(len(patterns), 1)
        self.assertEqual(str(patterns[0].pattern), 'mumble-ui/')

    def test_cube_extension_exposes_periodic_acl_sync(self):
        tasks = get_periodic_tasks()

        self.assertIn('mumble_fg.periodic_acl_sync', tasks)
