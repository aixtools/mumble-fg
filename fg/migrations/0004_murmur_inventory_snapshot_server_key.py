from django.db import migrations, models


def populate_server_key(apps, schema_editor):
    snapshot_model = apps.get_model("mumble_fg", "MurmurInventorySnapshot")
    for snapshot in snapshot_model.objects.all():
        server_id = getattr(snapshot, "server_id", None)
        server_name = str(getattr(snapshot, "server_name", "") or "").strip().lower()
        if server_id is None:
            server_key = server_name or "server-unknown"
        else:
            server_key = f"{server_name.replace(' ', '-') or 'server'}-{server_id}"
        snapshot.server_key = server_key
        snapshot.save(update_fields=["server_key"])


class Migration(migrations.Migration):

    dependencies = [
        ("mumble_fg", "0003_group_mapping_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="murmurinventorysnapshot",
            name="server_key",
            field=models.CharField(default="", max_length=255),
        ),
        migrations.RunPython(populate_server_key, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="murmurinventorysnapshot",
            name="server_id",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AlterModelOptions(
            name="murmurinventorysnapshot",
            options={"db_table": "fg_murmur_inventory_snapshot", "ordering": ["server_name", "server_key"]},
        ),
        migrations.AlterField(
            model_name="murmurinventorysnapshot",
            name="server_key",
            field=models.CharField(max_length=255, unique=True),
        ),
    ]
