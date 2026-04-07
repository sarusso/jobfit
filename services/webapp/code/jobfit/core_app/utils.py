import traceback
import random
import logging

logger = logging.getLogger(__name__)


def booleanize(*args, **kwargs):
    name = None
    if args and not kwargs:
        value = args[0]
    elif kwargs and not args:
        for item in kwargs:
            name  = item
            value = kwargs[item]
            break
    else:
        raise Exception('Internal Error')
    if name == value:
        return True
    if isinstance(value, bool):
        return value
    return value.upper() in ('TRUE', 'YES', 'Y', '1')


def format_exception(e):
    from django.conf import settings
    if settings.DEBUG:
        return 'Got exception "{}" of type "{}" with traceback:\n{}'.format(
            e.__class__.__name__, type(e), traceback.format_exc())[:-1]
    return 'Got exception "{}" of type "{}" with traceback "{}"'.format(
        e.__class__.__name__, type(e), traceback.format_exc().replace('\n', '|'))


def log_user_activity(level, msg, request, caller=None):
    try:
        msg = '{} view - USER {}: {}'.format(caller, request.user.email, msg)
    except AttributeError:
        msg = '{} view - USER UNKNOWN: {}'.format(caller, msg)
    logger.log(getattr(logging, level), msg)


def random_username():
    chars = 'qwertyuiopasdfghjklzxcvbnmQWERTYUIOPASDFGHJKLZXCVBNM0123456789'
    return ''.join(random.choice(chars) for _ in range(22))
