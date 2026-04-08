from ..utils import booleanize, random_username
from .common import BaseTestCase


class BooleanizeTest(BaseTestCase):

    def test_true_values(self):
        for v in (True, 'True', 'true', '1', 'yes'):
            self.assertTrue(booleanize(v), msg=f'Expected True for {v!r}')

    def test_false_values(self):
        for v in (False, 'False', 'false', '0', 'no', ''):
            self.assertFalse(booleanize(v), msg=f'Expected False for {v!r}')


class RandomUsernameTest(BaseTestCase):

    def test_returns_string(self):
        self.assertIsInstance(random_username(), str)

    def test_unique(self):
        names = {random_username() for _ in range(20)}
        self.assertEqual(len(names), 20)
