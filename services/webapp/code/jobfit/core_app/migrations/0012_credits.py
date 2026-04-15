from decimal import Decimal
from django.db import migrations, models


USD_PER_CREDIT = Decimal('0.10')  # $1 -> 10 credits


def convert_usd_to_credits(apps, schema_editor):
    TopUp    = apps.get_model('core_app', 'TopUp')
    UsageLog = apps.get_model('core_app', 'UsageLog')
    GiftCode = apps.get_model('core_app', 'GiftCode')

    for t in TopUp.objects.all():
        t.credits          = (t.amount_old   / USD_PER_CREDIT).quantize(Decimal('0.01'))
        t.residual_credits = (t.residual_old / USD_PER_CREDIT).quantize(Decimal('0.01'))
        t.save(update_fields=['credits', 'residual_credits'])

    for u in UsageLog.objects.all():
        u.usd_cost        = u.amount_old
        u.credits_charged = (u.amount_old / USD_PER_CREDIT).quantize(Decimal('0.01'))
        u.save(update_fields=['usd_cost', 'credits_charged'])

    for g in GiftCode.objects.all():
        g.credits = (g.amount_old / USD_PER_CREDIT).quantize(Decimal('0.01'))
        g.save(update_fields=['credits'])


def noop_reverse(apps, schema_editor):
    # Destructive rename: no reverse.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core_app', '0011_knownfit'),
    ]

    operations = [
        # Rename old columns to *_old so we can populate the new ones.
        migrations.RenameField('TopUp',    'amount',   'amount_old'),
        migrations.RenameField('TopUp',    'residual', 'residual_old'),
        migrations.RenameField('UsageLog', 'amount',   'amount_old'),
        migrations.RenameField('GiftCode', 'amount',   'amount_old'),

        # Add the new credit fields (nullable for the data migration).
        migrations.AddField(
            model_name='topup',
            name='credits',
            field=models.DecimalField(max_digits=10, decimal_places=2, null=True),
        ),
        migrations.AddField(
            model_name='topup',
            name='residual_credits',
            field=models.DecimalField(max_digits=10, decimal_places=2, null=True),
        ),
        migrations.AddField(
            model_name='usagelog',
            name='credits_charged',
            field=models.DecimalField(max_digits=10, decimal_places=2, null=True),
        ),
        migrations.AddField(
            model_name='usagelog',
            name='usd_cost',
            field=models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='giftcode',
            name='credits',
            field=models.DecimalField(max_digits=10, decimal_places=2, null=True),
        ),

        # Copy/convert data.
        migrations.RunPython(convert_usd_to_credits, noop_reverse),

        # Drop the old columns.
        migrations.RemoveField('TopUp',    'amount_old'),
        migrations.RemoveField('TopUp',    'residual_old'),
        migrations.RemoveField('UsageLog', 'amount_old'),
        migrations.RemoveField('GiftCode', 'amount_old'),

        # Enforce NOT NULL on the new credit fields now that they're populated.
        migrations.AlterField(
            model_name='topup',
            name='credits',
            field=models.DecimalField(max_digits=10, decimal_places=2),
        ),
        migrations.AlterField(
            model_name='topup',
            name='residual_credits',
            field=models.DecimalField(max_digits=10, decimal_places=2),
        ),
        migrations.AlterField(
            model_name='usagelog',
            name='credits_charged',
            field=models.DecimalField(max_digits=10, decimal_places=2),
        ),
        migrations.AlterField(
            model_name='giftcode',
            name='credits',
            field=models.DecimalField(max_digits=10, decimal_places=2),
        ),
    ]
