import os
from django.core.exceptions import ImproperlyConfigured
from jobfit.core_app.utils import booleanize

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '-3byo^nd6-x82fuj*#68mj=5#qp*gagg58sc($u$r-=g8ujxu4')
DEBUG = booleanize(os.environ.get('DJANGO_DEBUG', False))
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'jobfit.core_app',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'jobfit.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'jobfit.wsgi.application'

default_db_engine = 'django.db.backends.sqlite3'
default_db_name   = os.path.join(BASE_DIR, '../jobfit_database.sqlite3')

DATABASES = {
    'default': {
        'ENGINE':   os.environ.get('DJANGO_DB_ENGINE', default_db_engine),
        'NAME':     os.environ.get('DJANGO_DB_NAME', default_db_name),
        'USER':     os.environ.get('DJANGO_DB_USER', None),
        'PASSWORD': os.environ.get('DJANGO_DB_PASSWORD', None),
        'HOST':     os.environ.get('DJANGO_DB_HOST', None),
        'PORT':     os.environ.get('DJANGO_DB_PORT', None),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True

STATIC_URL  = '/static/'
STATIC_ROOT = '/jobfit/static'

# Project settings
MAIN_DOMAIN_NAME = os.environ.get('MAIN_DOMAIN_NAME', 'http://localhost')
CONTACT_EMAIL    = os.environ.get('CONTACT_EMAIL', 'contact@jobfit.app')
INVITATION_CODE  = os.environ.get('INVITATION_CODE', None)

try:
    TERMS_VERSION = float(os.environ.get('TERMS_VERSION', 1.0))
except Exception:
    raise ImproperlyConfigured('Invalid TERMS_VERSION, must be a float') from None

# Email
EMAIL_BACKEND       = os.environ.get('DJANGO_EMAIL_TYPE', 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST          = os.environ.get('DJANGO_EMAIL_HOST', None)
EMAIL_PORT          = int(os.environ.get('DJANGO_EMAIL_PORT', 587))
EMAIL_USE_TLS       = booleanize(os.environ.get('DJANGO_EMAIL_USE_TLS', True))
EMAIL_USE_SSL       = booleanize(os.environ.get('DJANGO_EMAIL_USE_SSL', False))
EMAIL_HOST_USER     = os.environ.get('DJANGO_EMAIL_HOST_USER', None)
EMAIL_HOST_PASSWORD = os.environ.get('DJANGO_EMAIL_HOST_PASSWORD', None)
DEFAULT_FROM_EMAIL  = os.environ.get('DJANGO_EMAIL_FROM', 'JobFit <notifications@jobfit.app>')

# Logging
DJANGO_LOG_LEVEL = os.environ.get('DJANGO_LOG_LEVEL', 'ERROR')
JOBFIT_LOG_LEVEL = os.environ.get('JOBFIT_LOG_LEVEL', 'ERROR')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'halfverbose': {
            'format': '%(asctime)s, %(name)s: [%(levelname)s] - %(message)s',
            'datefmt': '%m/%d/%Y %I:%M:%S %p',
        }
    },
    'filters': {
        'require_debug_false': {'()': 'django.utils.log.RequireDebugFalse'}
    },
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'halfverbose',
        },
    },
    'loggers': {
        'jobfit': {
            'handlers': ['console'],
            'level': JOBFIT_LOG_LEVEL,
            'propagate': False,
        },
        'django': {
            'handlers': ['console'],
            'level': DJANGO_LOG_LEVEL,
            'propagate': False,
        },
    },
}
