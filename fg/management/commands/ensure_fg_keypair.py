from __future__ import annotations

import os
import stat
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


def _chmod_exact(path: Path, mode: int) -> None:
    current = stat.S_IMODE(path.stat().st_mode)
    if current == mode:
        return
    path.chmod(mode)


class Command(BaseCommand):
    help = "Ensure FG keypair exists and permissions/symlink are normalized."

    def add_arguments(self, parser):
        parser.add_argument(
            "--etc-dir",
            default=os.environ.get("FG_ETC_DIR", "/etc/mumble-fg"),
            help="Base /etc directory (default: /etc/mumble-fg).",
        )
        parser.add_argument(
            "--key-dir",
            default=os.environ.get("FG_KEY_DIR", "/etc/mumble-fg/keys"),
            help="Directory containing private_key.pem/public_key.pem (default: /etc/mumble-fg/keys).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing keys (dangerous).",
        )
        parser.add_argument(
            "--no-passphrase",
            action="store_true",
            help="Generate an unencrypted private key if FG_PKI_PASSPHRASE is unset.",
        )

    def handle(self, *args, **options):
        etc_dir = Path(str(options["etc_dir"]))
        key_dir = Path(str(options["key_dir"]))
        force = bool(options["force"])
        no_passphrase = bool(options["no_passphrase"])

        private_path = key_dir / "private_key.pem"
        public_path = key_dir / "public_key.pem"
        public_link = etc_dir / "public_key.pem"

        # Ensure directories exist and have expected permissions.
        if not etc_dir.exists():
            raise CommandError(f"{etc_dir} does not exist (run setup-root.sh to create it)")
        if not key_dir.exists():
            raise CommandError(f"{key_dir} does not exist (run setup-root.sh to create it)")

        try:
            _chmod_exact(etc_dir, 0o755)
        except PermissionError as exc:
            raise CommandError(f"Cannot chmod {etc_dir} to 0755: {exc}") from exc
        try:
            _chmod_exact(key_dir, 0o700)
        except PermissionError as exc:
            raise CommandError(f"Cannot chmod {key_dir} to 0700: {exc}") from exc

        # Generate if missing.
        if force or (not private_path.exists()) or (not public_path.exists()):
            if (private_path.exists() or public_path.exists()) and not force:
                raise CommandError("Partial keypair exists; use --force to overwrite")
            from django.core.management import call_command
            call_command(
                "generate_fg_keypair",
                key_dir=str(key_dir),
                force=True,
                no_passphrase=no_passphrase,
            )

        # Normalize file permissions.
        if not private_path.exists() or not public_path.exists():
            raise CommandError(f"Expected key files not found in {key_dir}")

        try:
            _chmod_exact(private_path, 0o400)
        except PermissionError as exc:
            raise CommandError(f"Cannot chmod {private_path} to 0400: {exc}") from exc
        try:
            _chmod_exact(public_path, 0o444)
        except PermissionError as exc:
            raise CommandError(f"Cannot chmod {public_path} to 0444: {exc}") from exc

        # Ensure symlink exists and points at the public key file.
        try:
            if public_link.is_symlink() or public_link.exists():
                public_link.unlink()
            public_link.symlink_to(public_path)
        except PermissionError as exc:
            raise CommandError(f"Cannot create symlink {public_link} -> {public_path}: {exc}") from exc

        self.stdout.write(self.style.SUCCESS("FG keypair ready"))
        self.stdout.write(f"  private: {private_path} (0400)")
        self.stdout.write(f"  public:  {public_path} (0444)")
        self.stdout.write(f"  link:    {public_link} -> {public_path}")

