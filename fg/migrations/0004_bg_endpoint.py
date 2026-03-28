from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mumble_fg', '0003_group_mapping_models'),
    ]

    operations = [
        migrations.CreateModel(
            name='BgEndpoint',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True)),
                ('url', models.URLField(max_length=500)),
                ('psk', models.CharField(blank=True, default='', help_text='Per-endpoint PSK. If blank, falls back to global BG_PSK.', max_length=500)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'fg_bg_endpoint',
                'ordering': ['name'],
            },
        ),
    ]
