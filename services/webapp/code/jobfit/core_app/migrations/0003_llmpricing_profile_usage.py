import jobfit.core_app.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core_app', '0002_job_other'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='usage',
            field=jobfit.core_app.fields.JSONField(blank=True, default=dict),
        ),
        migrations.CreateModel(
            name='LLMPricing',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(max_length=50)),
                ('model', models.CharField(max_length=100)),
                ('price', jobfit.core_app.fields.JSONField()),
                ('superseded_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'ordering': ['-id'],
            },
        ),
    ]
