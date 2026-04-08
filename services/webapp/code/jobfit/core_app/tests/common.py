from django.test import TestCase, Client


class BaseTestCase(TestCase):

    def setUp(self):
        self.client = Client()

    def login(self, user):
        self.client.force_login(user)
