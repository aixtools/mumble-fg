from __future__ import annotations

import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Generate FG RSA keypair for decrypting BG->FG encrypted control secrets."

    def add_arguments(self, parser):
        parser.add_argument(
            "--key-dir",
            required=True,
            help="Directory to write private_key.pem and public_key.pem into.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing key files if they exist.",
        )
        parser.add_argument(
            "--no-passphrase",
            action="store_true",
            help="Write an unencrypted private key even if FG_PKI_PASSPHRASE is unset.",
        )

    def handle(self, *args, **options):
        key_dir = Path(str(options["key_dir"]))
        force = bool(options["force"])
        no_passphrase = bool(options["no_passphrase"])

        passphrase = (os.getenv("FG_PKI_PASSPHRASE") or "").strip()
        if not passphrase and not no_passphrase:
            raise CommandError("FG_PKI_PASSPHRASE is not set (use --no-passphrase to generate an unencrypted key)")

        private_path = key_dir / "private_key.pem"
        public_path = key_dir / "public_key.pem"

        if not force and (private_path.exists() or public_path.exists()):
            raise CommandError(f"Refusing to overwrite existing keys in {key_dir} (use --force)")

        key_dir.mkdir(parents=True, exist_ok=True)

        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization

        self.stdout.write("Generating 4096-bit RSA keypair...")
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)

        if passphrase:
            encryption = serialization.BestAvailableEncryption(passphrase.encode("utf-8"))
        else:
            encryption = serialization.NoEncryption()

        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=encryption,
        )
        public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        private_path.write_bytes(private_pem)
        public_path.write_bytes(public_pem)

        os.chmod(private_path, 0o600)
        os.chmod(public_path, 0o644)

        self.stdout.write(f"Private key: {private_path} (mode 0600)")
        self.stdout.write(f"Public key:  {public_path} (mode 0644)")
        self.stdout.write("")
        self.stdout.write("Set these in the FG environment:")
        self.stdout.write(f"  FG_PRIVATE_KEY_PATH={private_path}")
        self.stdout.write(f"  FG_PUBLIC_KEY_PATH={public_path}")

