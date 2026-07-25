from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mumble_fg', '0007_access_grants'),
    ]

    operations = [
        migrations.CreateModel(
            name='ServerPanelSettings',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('server_key', models.CharField(
                    help_text='BG server_key this tile belongs to.',
                    max_length=128,
                    unique=True,
                )),
                ('enabled', models.BooleanField(
                    default=True,
                    help_text=(
                        "Untick to hide this server's tile from every pilot. Voice access "
                        'is unaffected — only the profile/comms tile is hidden.'
                    ),
                )),
                ('label', models.CharField(
                    blank=True,
                    default='',
                    help_text=(
                        'Heading shown on the tile, e.g. "Mumble". Blank falls back to the '
                        'BG server name, then to the driver default.'
                    ),
                    max_length=64,
                )),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'fg_server_panel_settings',
                'ordering': ['server_key'],
                'verbose_name': 'Server Panel Settings',
                'verbose_name_plural': 'Server Panel Settings',
                'default_permissions': (),
                'permissions': [
                    ('view_server_panels', 'Can view Mumble server tile settings'),
                    ('change_server_panels', 'Can change Mumble server tile settings'),
                ],
            },
        ),
    ]
