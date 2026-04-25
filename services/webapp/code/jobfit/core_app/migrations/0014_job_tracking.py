from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core_app', '0013_usagelog_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='job',
            name='status',
            field=models.CharField(
                max_length=20,
                default='none',
                choices=[
                    ('none',         '—'),
                    ('to_apply',     'To apply'),
                    ('applied',      'Applied'),
                    ('in_progress',  'In progress'),
                    ('got_response', 'Got response'),
                ],
            ),
        ),
        migrations.AddField(
            model_name='job',
            name='status_updated_at',
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='job',
            name='applied_at',
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='job',
            name='notes',
            field=models.TextField(blank=True),
        ),
    ]
