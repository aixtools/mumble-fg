from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from fg.control import BgControlClient, BgSyncError, clear_handshake_throttle
from fg.models import ControlChannelKeyEntry


class Command(BaseCommand):
    help = (
        'Reset FG local FG/BG handshake state by clearing the FG control-key keyring. '
        'Use --bootstrap to immediately fetch a new key from BG.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset-handshake',
            action='store_true',
            help='Required acknowledgement for this sensitive reset operation.',
        )
        parser.add_argument(
            '--bootstrap',
            action='store_true',
            help='After reset, request a new encrypted session key from BG.',
        )

    def handle(self, *args, **options):
        if not options['reset_handshake']:
            raise CommandError('Refusing to run without --reset-handshake.')

        key_count_before = ControlChannelKeyEntry.objects.count()
        ControlChannelKeyEntry.objects.all().delete()
        clear_handshake_throttle()

        summary = (
            f'FG handshake reset complete '
            f'(cleared_key_entries={key_count_before}, bootstrap={bool(options["bootstrap"])})'
        )

        if not options['bootstrap']:
            self.stdout.write(self.style.SUCCESS(summary))
            return

        client = BgControlClient()
        try:
            key_id = client.bootstrap_control_key(requested_by='fg.reset_fgbg_handshake')
        except BgSyncError as exc:
            raise CommandError(f'{summary}; bootstrap failed: {exc}') from exc

        self.stdout.write(self.style.SUCCESS(f'{summary}, key_id={key_id}'))
