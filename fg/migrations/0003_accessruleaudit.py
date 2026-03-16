from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mumble_fg', '0002_rename_block_to_deny'),
    ]

    operations = [
        migrations.CreateModel(
            name='AccessRuleAudit',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('acl_id', models.IntegerField(blank=True, help_text='ACL primary key at the time of the audit event.', null=True)),
                ('action', models.CharField(choices=[('create', 'Create'), ('update', 'Update'), ('delete', 'Delete'), ('sync', 'Sync')], max_length=16)),
                ('actor_username', models.CharField(blank=True, default='', help_text='Username that initiated the change.', max_length=255)),
                ('source', models.CharField(blank=True, default='', help_text='Originating FG surface (e.g. ACL UI or admin).', max_length=64)),
                ('entity_id', models.BigIntegerField(blank=True, help_text='EVE Online ID (alliance, corporation, or character) when tied to one ACL row.', null=True)),
                ('entity_type', models.CharField(blank=True, choices=[('alliance', 'Alliance'), ('corporation', 'Corporation'), ('pilot', 'Pilot')], max_length=16, null=True)),
                ('deny', models.BooleanField(blank=True, null=True)),
                ('note', models.TextField(blank=True, default='')),
                ('acl_created_by', models.CharField(blank=True, default='', help_text='Original creator recorded on the active ACL row.', max_length=255)),
                ('previous', models.JSONField(blank=True, default=dict, help_text='Prior ACL row snapshot for update events.')),
                ('metadata', models.JSONField(blank=True, default=dict, help_text='Additional event context such as sync trigger and BG response summary.')),
                ('occurred_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'fg_access_rule_audit',
                'ordering': ['-occurred_at', '-id'],
                'verbose_name': 'access control audit entry',
                'verbose_name_plural': 'access control audit log',
            },
        ),
    ]
