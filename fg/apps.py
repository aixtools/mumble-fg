from django.apps import AppConfig
import logging


class MumbleFgConfig(AppConfig):
    name = 'fg'
    label = 'mumble_fg'
    verbose_name = 'Mumble Foreground'

    def ready(self):
        pki_logger = logging.getLogger('fg.pki')
        from fg import crypto
        if not crypto.is_available():
            try:
                crypto.initialize()
            except Exception:
                pass
        if not crypto.is_available():
            try:
                crypto.fetch_from_bg()
            except Exception:
                logging.getLogger('fg.crypto').info('BG public key not available at startup')

        # FG PKI is optional; used to decrypt BG->FG key exports and other
        # sensitive responses once 2-way comms are enabled.
        try:
            from fg import pki
            if not pki.is_initialized():
                pki.initialize()
        except Exception as exc:
            status = pki.startup_status()
            pki_logger.warning(
                'FG PKI startup failed: reason=%s private_key_path_present=%s '
                'private_key_exists=%s public_key_path_present=%s public_key_exists=%s '
                'passphrase_present=%s can_decrypt=%s',
                exc,
                status.get('private_key_path_present'),
                status.get('private_key_exists'),
                status.get('public_key_path_present'),
                status.get('public_key_exists'),
                status.get('passphrase_present'),
                status.get('can_decrypt'),
            )
        else:
            status = pki.startup_status()
            pki_logger.info(
                'FG PKI startup status: private_key_path_present=%s private_key_exists=%s '
                'public_key_path_present=%s public_key_exists=%s passphrase_present=%s '
                'can_decrypt=%s',
                status.get('private_key_path_present'),
                status.get('private_key_exists'),
                status.get('public_key_path_present'),
                status.get('public_key_exists'),
                status.get('passphrase_present'),
                status.get('can_decrypt'),
            )
