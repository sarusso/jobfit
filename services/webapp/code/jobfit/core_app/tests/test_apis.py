from decimal import Decimal
from django.utils import timezone

from ..models import User, Profile, GiftCode, TopUp
from .common import BaseTestCase


class AuthTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('testuser', email='test@example.com', password='testpass')
        Profile.objects.create(user=self.user)

    def test_login_get_redirects_authenticated(self):
        self.login(self.user)
        resp = self.client.get('/login/')
        self.assertEqual(resp.status_code, 302)

    def test_login_post_valid(self):
        resp = self.client.post('/login/', {'username': 'test@example.com', 'password': 'testpass'})
        self.assertEqual(resp.status_code, 302)

    def test_login_post_wrong_password(self):
        resp = self.client.post('/login/', {'username': 'test@example.com', 'password': 'wrong'})
        self.assertEqual(resp.status_code, 200)

    def test_account_requires_login(self):
        resp = self.client.get('/account/')
        self.assertEqual(resp.status_code, 302)

    def test_account_accessible_when_logged_in(self):
        self.login(self.user)
        resp = self.client.get('/account/')
        self.assertEqual(resp.status_code, 200)


class GiftCodeRedemptionTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('testuser', email='test@example.com', password='testpass')
        Profile.objects.create(user=self.user)
        self.login(self.user)

    def _make_code(self, code='GIFT-CODE', amount='5.00', days_valid=30, validity_days=None):
        return GiftCode.objects.create(
            code=code,
            amount=Decimal(amount),
            expires_at=timezone.now() + timezone.timedelta(days=days_valid),
            validity_days=validity_days,
        )

    def test_redeem_valid_code(self):
        self._make_code()
        resp = self.client.post('/account/redeem/', {'code': 'GIFT-CODE'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(TopUp.objects.filter(user=self.user).count(), 1)
        self.assertEqual(TopUp.objects.get(user=self.user).residual, Decimal('5.00'))

    def test_redeem_case_insensitive(self):
        self._make_code()
        self.client.post('/account/redeem/', {'code': 'gift-code'})
        self.assertEqual(TopUp.objects.filter(user=self.user).count(), 1)

    def test_redeem_invalid_code(self):
        resp = self.client.post('/account/redeem/', {'code': 'WRONG'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(TopUp.objects.filter(user=self.user).count(), 0)

    def test_redeem_expired_code(self):
        GiftCode.objects.create(
            code='OLD-CODE',
            amount=Decimal('5.00'),
            expires_at=timezone.now() - timezone.timedelta(days=1),
        )
        self.client.post('/account/redeem/', {'code': 'OLD-CODE'})
        self.assertEqual(TopUp.objects.filter(user=self.user).count(), 0)

    def test_redeem_already_redeemed(self):
        code = self._make_code()
        self.client.post('/account/redeem/', {'code': 'GIFT-CODE'})
        another = User.objects.create_user('other', email='other@example.com', password='pass')
        Profile.objects.create(user=another)
        self.client.force_login(another)
        self.client.post('/account/redeem/', {'code': 'GIFT-CODE'})
        self.assertEqual(TopUp.objects.filter(user=another).count(), 0)

    def test_redeem_with_validity_days_sets_expiry(self):
        self._make_code(validity_days=2)
        self.client.post('/account/redeem/', {'code': 'GIFT-CODE'})
        topup = TopUp.objects.get(user=self.user)
        self.assertIsNotNone(topup.expires_at)

    def test_redeem_without_validity_days_no_expiry(self):
        self._make_code(validity_days=None)
        self.client.post('/account/redeem/', {'code': 'GIFT-CODE'})
        topup = TopUp.objects.get(user=self.user)
        self.assertIsNone(topup.expires_at)
