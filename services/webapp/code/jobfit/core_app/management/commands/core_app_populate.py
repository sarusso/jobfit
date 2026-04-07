from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from ...models import Profile
from django.conf import settings


class Command(BaseCommand):
    help = 'Creates a test admin user for development.'

    def handle(self, *args, **options):

        try:
            testuser = User.objects.get(username='testuser')
            print('Test user already exists, skipping.')
        except User.DoesNotExist:
            print('Creating test user...')
            testuser = User.objects.create_user('testuser', 'testuser@jobfit.app', 'testpass')
            testuser.is_staff = True
            testuser.is_superuser = True
            testuser.save()
            Profile.objects.create(
                user=testuser,
                email_updates=False,
                last_accepted_terms=settings.TERMS_VERSION,
            )
            print('Done. Email: testuser@jobfit.app  Password: testpass')
