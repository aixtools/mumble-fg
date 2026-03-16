from django.core.management.base import BaseCommand, CommandError

from fg.control import MurmurSyncError
from fg.tasks import periodic_acl_sync


class Command(BaseCommand):
    help = 'Synchronize the FG ACL decision table to BG and append a sync audit entry'

    def handle(self, *args, **options):
        try:
            response = periodic_acl_sync()
        except MurmurSyncError as exc:
            raise CommandError(f'ACL sync failed: {exc}') from exc

        total = response.get('total')
        if not isinstance(total, int):
            total = 'unknown'
        self.stdout.write(self.style.SUCCESS(f'ACL synchronized to BG ({total} entries).'))
