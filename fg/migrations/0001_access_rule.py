from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='AccessRule',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('entity_id', models.BigIntegerField(help_text='EVE Online ID (alliance, corporation, or character).', unique=True)),
                ('entity_type', models.CharField(
                    choices=[('alliance', 'Alliance'), ('corporation', 'Corporation'), ('pilot', 'Pilot')],
                    help_text='Deducible from ID range but kept for query convenience.',
                    max_length=16,
                )),
                ('block', models.BooleanField(default=False, help_text='False = permit (default). True = deny access.')),
                ('note', models.TextField(blank=True, default='', help_text='Admin notes (e.g. reason for block, ticket reference).')),
                ('created_by', models.CharField(blank=True, default='', help_text='Who added this rule.', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'fg_access_rule',
                'ordering': ['entity_type', 'entity_id'],
            },
        ),
    ]
