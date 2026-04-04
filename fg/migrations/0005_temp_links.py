from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mumble_fg", "0004_murmur_inventory_snapshot_server_key"),
    ]

    operations = [
        migrations.CreateModel(
            name="TempLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(blank=True, default="", max_length=255)),
                ("token", models.CharField(max_length=64, unique=True)),
                ("server_key", models.CharField(max_length=255)),
                ("server_name", models.CharField(blank=True, default="", max_length=255)),
                ("groups_csv", models.TextField(blank=True, default="Guest")),
                ("max_uses", models.PositiveIntegerField(blank=True, null=True)),
                ("use_count", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("expires_at", models.DateTimeField()),
                ("last_redeemed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by_username", models.CharField(blank=True, default="", max_length=255)),
            ],
            options={
                "db_table": "fg_temp_link",
                "ordering": ["-created_at", "-id"],
                "default_permissions": (),
                "permissions": [
                    ("view_temp_links", "Can view Mumble temp links"),
                    ("change_temp_links", "Can change Mumble temp links"),
                    ("add_temp_links", "Can add Mumble temp links"),
                    ("delete_temp_links", "Can delete Mumble temp links"),
                ],
            },
        ),
    ]
