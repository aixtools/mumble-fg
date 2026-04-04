from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mumble_fg', '0005_temp_links'),
    ]

    operations = [
        migrations.CreateModel(
            name='TempLinkSettings',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ],
            options={
                'db_table': 'fg_temp_link_settings',
                'verbose_name': 'Temp Link Settings',
                'verbose_name_plural': 'Temp Link Settings',
            },
        ),
        migrations.AddField(
            model_name='templinksettings',
            name='editor_groups',
            field=models.ManyToManyField(
                blank=True,
                help_text='Groups allowed to create and manage temp links',
                related_name='temp_link_settings',
                to='accounts.Group',
            ),
        ),
    ]
