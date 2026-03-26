from django.apps import AppConfig


class MumbleFgConfig(AppConfig):
    name = 'fg'
    label = 'mumble_fg'
    verbose_name = 'Mumble Foreground'

    def ready(self):
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
                import logging
                logging.getLogger('fg.crypto').info('BG public key not available at startup')

        # FG PKI is optional; used to decrypt BG->FG key exports and other
        # sensitive responses once 2-way comms are enabled.
        try:
            from fg import pki
            if not pki.is_initialized():
                pki.initialize()
        except Exception:
            pass
