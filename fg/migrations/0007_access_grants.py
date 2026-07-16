from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mumble_fg', '0006_temp_link_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='accessrule',
            name='source',
            field=models.CharField(
                choices=[('manual', 'Manual'), ('group_grant', 'Group grant')],
                default='manual',
                help_text=(
                    'group_grant rules are owned by the Cube-group reconciler and '
                    'auto-removed when the pilot leaves the granting group. Any '
                    'manual edit re-marks the rule as manual.'
                ),
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name='AccessGrantSettings',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ],
            options={
                'db_table': 'fg_access_grant_settings',
                'verbose_name': 'Access Grant Settings',
                'verbose_name_plural': 'Access Grant Settings',
            },
        ),
        migrations.AddField(
            model_name='accessgrantsettings',
            name='grant_groups',
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    'Approved members of these Cube groups get an automatic '
                    'Mumble pilot allow rule for their main character.'
                ),
                related_name='access_grant_settings',
                to='accounts.Group',
            ),
        ),
    ]
