from django.core.management.base import BaseCommand

from fg.pilot.models import MumbleUser
from fg.views import _compute_display_name


class Command(BaseCommand):
    help = 'Backfill empty display_name fields on active MumbleUser records'

    def handle(self, *args, **options):
        qs = MumbleUser.objects.filter(is_active=True, display_name='').select_related('user')
        total = qs.count()
        if total == 0:
            self.stdout.write('No active MumbleUser records with empty display_name.')
            return

        self.stdout.write(f'Found {total} record(s) to backfill...')
        updated = 0
        for mu in qs:
            display_name = _compute_display_name(mu.user)
            if display_name:
                mu.display_name = display_name
                mu.save(update_fields=['display_name', 'updated_at'])
                updated += 1
                self.stdout.write(f'  {mu.username} -> {display_name}')

        self.stdout.write(self.style.SUCCESS(f'Done. Updated {updated}/{total} records.'))
