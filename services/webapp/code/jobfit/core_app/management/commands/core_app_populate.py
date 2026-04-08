from django.core.management.base import BaseCommand
from ...models import User, Profile, LLMPricing
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

        # LLM pricing — create if no active rows exist
        _PRICING = [
            ("openai", "gpt-4o",      {"completion_tokens": 10.0, "prompt_tokens": 2.5}),
            ("openai", "gpt-4o-mini", {"completion_tokens": 0.6,  "prompt_tokens": 0.15}),
        ]
        for provider, model, price in _PRICING:
            if not LLMPricing.objects.filter(provider=provider, model=model, superseded_at__isnull=True).exists():
                LLMPricing.objects.create(provider=provider, model=model, price=price)
                print(f'Created LLMPricing for {provider}/{model}.')
            else:
                print(f'LLMPricing for {provider}/{model} already exists, skipping.')
