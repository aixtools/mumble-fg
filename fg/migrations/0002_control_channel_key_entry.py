from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mumble_fg", "0001_acl_admin_and_pilot_snapshot_hash"),
    ]

    operations = [
        migrations.CreateModel(
            name="ControlChannelKeyEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key_id", models.UUIDField(unique=True)),
                (
                    "secret_ciphertext_b64",
                    models.TextField(
                        help_text="Base64 RSA ciphertext of the control secret (encrypted with FG public key)."
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "fg_control_channel_key_entry",
                "ordering": ["-created_at", "-id"],
            },
        ),
    ]
