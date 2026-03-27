from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mumble_fg", "0002_control_channel_key_entry"),
    ]

    operations = [
        migrations.CreateModel(
            name="CubeGroupMapping",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cube_group_name", models.CharField(max_length=255)),
                ("murmur_group_name", models.CharField(max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "fg_cube_group_mapping",
                "ordering": ["cube_group_name", "murmur_group_name"],
                "default_permissions": (),
                "permissions": [
                    ("view_group_mapping", "Can view Cube-to-Murmur group mappings"),
                    ("change_group_mapping", "Can change Cube-to-Murmur group mappings"),
                    ("add_group_mapping", "Can add Cube-to-Murmur group mappings"),
                    ("delete_group_mapping", "Can delete Cube-to-Murmur group mappings"),
                ],
            },
        ),
        migrations.CreateModel(
            name="IgnoredCubeGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cube_group_name", models.CharField(max_length=255, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "fg_ignored_cube_group",
                "ordering": ["cube_group_name"],
            },
        ),
        migrations.CreateModel(
            name="IgnoredMurmurGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("murmur_group_name", models.CharField(max_length=255, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "fg_ignored_murmur_group",
                "ordering": ["murmur_group_name"],
            },
        ),
        migrations.CreateModel(
            name="MurmurInventorySnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("server_id", models.PositiveIntegerField(unique=True)),
                ("server_name", models.CharField(blank=True, default="", max_length=255)),
                ("freshness_seconds", models.PositiveIntegerField(default=600)),
                ("is_real_time", models.BooleanField(default=False)),
                ("fetched_at", models.DateTimeField(blank=True, null=True)),
                ("inventory", models.JSONField(blank=True, default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "fg_murmur_inventory_snapshot",
                "ordering": ["server_id"],
            },
        ),
        migrations.AddConstraint(
            model_name="cubegroupmapping",
            constraint=models.UniqueConstraint(
                fields=("cube_group_name", "murmur_group_name"),
                name="fg_cube_group_mapping_unique_pair",
            ),
        ),
    ]
