import uuid
import logging

from django.shortcuts import render
from django.http import HttpResponse, HttpResponseRedirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.conf import settings
from django.core.mail import send_mail

from .decorators import public_view, private_view
from .exceptions import ErrorMessage
from .utils import booleanize, random_username
from .models import LoginToken, Profile

logger = logging.getLogger(__name__)

ONGOING_SIGNUPS = {}


#=========================
#  Home
#=========================

@public_view
def home(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect('/postlogin/')
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
                        raise ErrorMessage('Check email and password')
                    else:
                        data['success'] = 'If we have your address on file you will receive a login link shortly.'
                        return render(request, 'login.html', {'data': data})

            if password:
                user = authenticate(username=username, password=password)
                if user:
                    login(request, user)
                    return HttpResponseRedirect('/postlogin/')
                else:
                    raise ErrorMessage('Check email and password')
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

    if profile.last_accepted_terms < settings.TERMS_VERSION:
        accepted = booleanize(request.GET.get('accepted', False))
        if accepted:
            profile.last_accepted_terms = settings.TERMS_VERSION
            profile.save()
            return HttpResponseRedirect('/account/')
        data = {'action': 'accept_terms'}
        return render(request, 'postlogin.html', {'data': data})

    return HttpResponseRedirect('/account/')


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

    edit = request.GET.get('edit', None) or request.POST.get('edit', None)
    data['edit'] = edit

    if request.method == 'POST':
        value = request.POST.get('value', None)

        if edit == 'email':
            if value and '@' in value:
                request.user.email = value
                request.user.save()
                data['success'] = 'Email updated.'
            else:
                raise ErrorMessage('Invalid email address.')

        elif edit == 'password':
            if value and len(value) >= 6:
                request.user.set_password(value)
                request.user.save()
                # Re-login after password change
                user = authenticate(username=request.user.username, password=value)
                if user:
                    login(request, user)
                data['success'] = 'Password updated.'
            else:
                raise ErrorMessage('Password must be at least 6 characters.')

        elif edit == 'email_preferences':
            profile.email_updates = booleanize(request.POST.get('email_updates', False))
            profile.save()
            data['success'] = 'Preferences saved.'

        elif edit == 'delete_account':
            if value == request.user.username:
                request.user.delete()
                logout(request)
                return HttpResponseRedirect('/')
            else:
                raise ErrorMessage('Account ID did not match.')

        data['edit'] = None

    return render(request, 'account.html', {'data': data})


#=========================
#  Privacy / Terms
#=========================

@public_view
def privacy(request):
    return render(request, 'privacy.html', {'data': {'user': request.user}})


@public_view
def terms(request):
    return render(request, 'terms.html', {'data': {'user': request.user}})
