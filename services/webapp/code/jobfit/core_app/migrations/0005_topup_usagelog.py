import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core_app', '0004_giftcode_creditledger'),
    ]

    operations = [
        # Drop the old CreditLedger (superseded by TopUp + UsageLog)
        migrations.DeleteModel(name='CreditLedger'),

        # Add validity_days to GiftCode
        migrations.AddField(
            model_name='giftcode',
            name='validity_days',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),

        # TopUp
        migrations.CreateModel(
            name='TopUp',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='topups', to=settings.AUTH_USER_MODEL)),
                ('amount',   models.DecimalField(decimal_places=4, max_digits=10)),
                ('residual', models.DecimalField(decimal_places=4, max_digits=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={'ordering': ['expires_at', 'created_at']},
        ),

        # UsageLog
        migrations.CreateModel(
            name='UsageLog',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='usage_logs', to=settings.AUTH_USER_MODEL)),
                ('amount',      models.DecimalField(decimal_places=4, max_digits=10)),
                ('description', models.CharField(max_length=255)),
                ('created_at',  models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
