import uuid
import logging
from datetime import timedelta
from decimal import Decimal

from django.shortcuts import render
from django.http import HttpResponse, HttpResponseRedirect
from django.contrib.auth import authenticate, login, logout
from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.db.models import F, Q, Sum
from django.utils import timezone

from .decorators import public_view, private_view
from .exceptions import ErrorMessage
from .utils import booleanize, random_username
from .models import User, LoginToken, Profile, LLMPricing, GiftCode, TopUp, UsageLog


def _compute_usage_cost(usage: dict) -> float:
    """Compute total cost in USD from a Profile.usage JSON dict."""
    pricing_lookup = {
        (p.provider, p.model, p.pricing_key()): p.price
        for p in LLMPricing.objects.all()
    }
    total = 0.0
    for provider, models in usage.items():
        for model, keys in models.items():
            for key, tokens in keys.items():
                price = pricing_lookup.get((provider, model, key), {})
                for token_type, count in tokens.items():
                    total += count * price.get(token_type, 0) / 1_000_000
    return total

logger = logging.getLogger(__name__)

ONGOING_SIGNUPS = {}


#=========================
#  Home
#=========================

@public_view
def home(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect('/jobs/')
    data = {'user': request.user}
    return render(request, 'home.html', {'data': data})


#=========================
#  Login
#=========================

@public_view
def user_login(request):
    data = {}

    if request.method == 'GET' and request.user.is_authenticated:
        return HttpResponseRedirect('/postlogin/')

    if request.method == 'POST':
        if not request.user.is_authenticated:
            username = request.POST.get('username', '')
            password = request.POST.get('password', '')

            if '@' in username:
                try:
                    user = User.objects.get(email=username)
                    username = user.username
                except User.DoesNotExist:
                    if password:
                        data['error'] = 'Check email and password'
                        data['email'] = request.POST.get('username', '')
                        return render(request, 'login.html', {'data': data})
                    else:
                        data['success'] = 'If we have your address on file you will receive a login link shortly.'
                        return render(request, 'login.html', {'data': data})

            if password:
                user = authenticate(username=username, password=password)
                if user:
                    login(request, user)
                    return HttpResponseRedirect('/postlogin/')
                else:
                    data['error'] = 'Check email and password'
                    data['email'] = request.POST.get('username', '')
                    return render(request, 'login.html', {'data': data})
            else:
                # Passwordless login via email token
                try:
                    user = User.objects.get(username=username)
                except User.DoesNotExist:
                    data['success'] = 'If we have your address on file you will receive a login link shortly.'
                    return render(request, 'login.html', {'data': data})

                token = str(uuid.uuid4())
                try:
                    login_token = LoginToken.objects.get(user=user)
                    login_token.token = token
                    login_token.save()
                except LoginToken.DoesNotExist:
                    LoginToken.objects.create(user=user, token=token)

                try:
                    send_mail(
                        subject='JobFit login link',
                        message='Hello,\n\nHere is your login link: {}/login/?token={}\n\nOnce logged in you can set a password in your account page.'.format(
                            settings.MAIN_DOMAIN_NAME, token),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[user.email],
                        fail_silently=False,
                    )
                except Exception as e:
                    logger.error('Failed to send login email: %s', e)

                data['success'] = 'If we have your address on file you will receive a login link shortly.'
                return render(request, 'login.html', {'data': data})
        else:
            logout(request)

    else:
        token = request.GET.get('token', None)
        if token:
            tokens = LoginToken.objects.filter(token=token)
            if not tokens:
                raise ErrorMessage('Token not valid or expired')
            if len(tokens) > 1:
                raise Exception('Consistency error: multiple users with same token')
            login_token = tokens[0]
            user = login_token.user
            user.backend = 'django.contrib.auth.backends.ModelBackend'
            login(request, user)
            login_token.delete()
            return HttpResponseRedirect('/postlogin/')

    return render(request, 'login.html', {'data': data})


#=========================
#  Logout
#=========================

@private_view
def user_logout(request):
    logout(request)
    return HttpResponseRedirect('/')


#=========================
#  Register
#=========================

@public_view
def register(request):
    data = {}
    data['user']   = request.user
    data['status'] = None
    data['require_invitation'] = bool(settings.INVITATION_CODE)

    if request.user.is_authenticated:
        return HttpResponseRedirect('/postlogin/')

    email      = request.POST.get('email', None)
    password   = request.POST.get('password', None)
    invitation = request.POST.get('invitation', None)

    if email and password:
        if settings.INVITATION_CODE and invitation != settings.INVITATION_CODE:
            raise ErrorMessage('The invitation code you entered is not valid.')

        if email not in ONGOING_SIGNUPS:
            ONGOING_SIGNUPS[email] = None
            try:
                if User.objects.filter(email=email).exists():
                    raise ErrorMessage('That email address is already registered.')

                terms_accepted = request.POST.get('terms_accepted', None)
                if not terms_accepted:
                    raise ErrorMessage('You must accept the Terms of Service and Privacy Policy to register.')

                email_updates = booleanize(request.POST.get('email_updates', False))

                user = User.objects.create_user(random_username(), password=password, email=email)
                user.backend = 'django.contrib.auth.backends.ModelBackend'
                login(request, user)

                Profile.objects.create(
                    user=user,
                    email_updates=email_updates,
                    last_accepted_terms=settings.TERMS_VERSION,
                    last_accepted_privacy=settings.PRIVACY_VERSION,
                )

                data['status'] = 'activated'
                data['user']   = user
            finally:
                if email in ONGOING_SIGNUPS:
                    del ONGOING_SIGNUPS[email]

            return render(request, 'register.html', {'data': data})

    return render(request, 'register.html', {'data': data})


#=========================
#  Post-login
#=========================

@private_view
def postlogin(request):
    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        Profile.objects.create(user=request.user)
        profile = request.user.profile

    needs_terms   = profile.last_accepted_terms   < settings.TERMS_VERSION
    needs_privacy = profile.last_accepted_privacy < settings.PRIVACY_VERSION

    if needs_terms or needs_privacy:
        accepted = booleanize(request.GET.get('accepted', False))
        if accepted:
            if needs_terms:
                profile.last_accepted_terms = settings.TERMS_VERSION
            if needs_privacy:
                profile.last_accepted_privacy = settings.PRIVACY_VERSION
            profile.save()
            return HttpResponseRedirect('/jobs/')
        data = {'action': 'accept_terms'}
        return render(request, 'postlogin.html', {'data': data})

    return HttpResponseRedirect('/jobs/')


#=========================
#  Account
#=========================

@private_view
def account(request):
    data = {}
    data['user'] = request.user

    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        Profile.objects.create(user=request.user)
        profile = request.user.profile
    data['profile'] = profile

    edit = request.POST.get('edit', None)
    if not edit:
        edit = request.GET.get('edit', None)
    data['edit'] = edit

    value = request.POST.get('value', None)

    if request.method == 'POST' and edit:

        if edit == 'email' and value:
            request.user.email = value
            request.user.save()

        elif edit == 'password' and value:
            request.user.set_password(value)
            request.user.save()
            user = authenticate(username=request.user.username, password=value)
            if user:
                login(request, user)

        elif edit == 'timezone' and value:
            profile.timezone = value
            profile.save()

        elif edit == 'type' and value:
            profile.type = value
            profile.save()

        elif edit == 'email_preferences':
            if booleanize(request.POST.get('do_update', False)):
                profile.email_updates = booleanize(request.POST.get('email_updates', False))
                profile.save()

        elif edit == 'delete_account' and value:
            if value == request.user.username:
                request.user.delete()
                logout(request)
                return HttpResponseRedirect('/')
            else:
                raise ErrorMessage('Account ID did not match.')

        data['edit'] = None

    data['total_cost'] = _compute_usage_cost(profile.usage or {})
    data['balance']    = profile.get_balance()
    data['topups']     = TopUp.objects.filter(user=request.user).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    ).order_by(F('expires_at').asc(nulls_last=True))
    _now = timezone.now()
    all_topups = TopUp.objects.filter(user=request.user).order_by('-created_at')
    for t in all_topups:
        t.is_expired = t.expires_at is not None and t.expires_at < _now
    data['all_topups'] = all_topups
    data['usage_log']  = UsageLog.objects.filter(user=request.user)[:20]

    return render(request, 'account.html', {'data': data})


#=========================
#  Gift code redemption
#=========================

@private_view
def redeem_gift_code(request):
    if request.method != 'POST':
        return HttpResponseRedirect('/account/')

    code_str = request.POST.get('code', '').strip()
    if not code_str:
        messages.warning(request, 'Please enter a gift code.')
        return HttpResponseRedirect('/account/')

    from django.db import transaction
    try:
        with transaction.atomic():
            try:
                gift = GiftCode.objects.select_for_update().get(code__iexact=code_str)
            except GiftCode.DoesNotExist:
                messages.warning(request, 'Invalid gift code.')
                return HttpResponseRedirect('/account/')

            if gift.redeemed_by_id is not None:
                messages.warning(request, 'This code has already been redeemed.')
                return HttpResponseRedirect('/account/')

            if gift.expires_at < timezone.now():
                messages.warning(request, 'This gift code has expired.')
                return HttpResponseRedirect('/account/')

            now = timezone.now()
            gift.redeemed_by = request.user
            gift.redeemed_at = now
            gift.save(update_fields=['redeemed_by', 'redeemed_at'])

            expires_at = (
                now + timedelta(days=gift.validity_days)
                if gift.validity_days else None
            )
            TopUp.objects.create(
                user=request.user,
                amount=gift.amount,
                residual=gift.amount,
                expires_at=expires_at,
            )
    except Exception as e:
        logger.error('Gift code redemption error: %s', e)
        messages.warning(request, 'An error occurred. Please try again.')
        return HttpResponseRedirect('/account/')

    messages.success(request, f'${gift.amount:.2f} added to your account.')
    return HttpResponseRedirect('/account/')


#=========================
#  Privacy / Terms
#=========================

@public_view
def privacy(request):
    return render(request, 'privacy.html', {'data': {'user': request.user}})


@public_view
def terms(request):
    return render(request, 'terms.html', {'data': {'user': request.user}})
