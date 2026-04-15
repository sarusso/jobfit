from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core_app', '0012_credits'),
    ]

    operations = [
        migrations.AddField(
            model_name='usagelog',
            name='type',
            field=models.IntegerField(
                null=True, blank=True, default=None,
                choices=[(0, 'Job import'), (1, 'CV scoring')],
            ),
        ),
    ]
