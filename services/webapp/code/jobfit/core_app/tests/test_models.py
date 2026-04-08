from decimal import Decimal
from django.utils import timezone

from ..models import User, Profile, GiftCode, TopUp, UsageLog
from .common import BaseTestCase


class ProfileBalanceTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('testuser', email='test@example.com', password='testpass')
        Profile.objects.create(user=self.user)

    def test_balance_no_topups(self):
        self.assertEqual(self.user.profile.get_balance(), Decimal('0'))

    def test_balance_with_topup(self):
        TopUp.objects.create(user=self.user, amount=Decimal('5.00'), residual=Decimal('5.00'))
        self.assertEqual(self.user.profile.get_balance(), Decimal('5.00'))

    def test_balance_partial_residual(self):
        TopUp.objects.create(user=self.user, amount=Decimal('5.00'), residual=Decimal('3.00'))
        self.assertEqual(self.user.profile.get_balance(), Decimal('3.00'))

    def test_balance_multiple_topups(self):
        TopUp.objects.create(user=self.user, amount=Decimal('5.00'), residual=Decimal('5.00'))
        TopUp.objects.create(user=self.user, amount=Decimal('2.00'), residual=Decimal('2.00'))
        self.assertEqual(self.user.profile.get_balance(), Decimal('7.00'))

    def test_expired_topup_excluded(self):
        past = timezone.now() - timezone.timedelta(days=1)
        TopUp.objects.create(user=self.user, amount=Decimal('5.00'), residual=Decimal('5.00'), expires_at=past)
        self.assertEqual(self.user.profile.get_balance(), Decimal('0'))

    def test_zero_residual_excluded(self):
        TopUp.objects.create(user=self.user, amount=Decimal('5.00'), residual=Decimal('0'))
        self.assertEqual(self.user.profile.get_balance(), Decimal('0'))

    def test_future_expiry_included(self):
        future = timezone.now() + timezone.timedelta(days=2)
        TopUp.objects.create(user=self.user, amount=Decimal('5.00'), residual=Decimal('5.00'), expires_at=future)
        self.assertEqual(self.user.profile.get_balance(), Decimal('5.00'))


class GiftCodeTest(BaseTestCase):

    def test_gift_code_creation(self):
        future = timezone.now() + timezone.timedelta(days=30)
        code = GiftCode.objects.create(code='TEST-CODE', amount=Decimal('10.00'), expires_at=future)
        self.assertIsNone(code.redeemed_by)
        self.assertIsNone(code.redeemed_at)
        self.assertIsNone(code.validity_days)
