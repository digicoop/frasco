from frasco.ext import *
from frasco.utils import import_string
from frasco.models import delayed_tx_calls
from flask_rq2 import RQ
from flask_rq2 import cli
from rq import get_current_job
from rq.timeouts import JobTimeoutException
from .job import FrascoJob
import redis.exceptions
import functools
import logging


logger = logging.getLogger('frasco.tasks')


class FrascoTasks(Extension):
    name = 'frasco_tasks'
    prefix_extra_options = 'RQ_'
    defaults = {"tasks_timeout": RQ.default_timeout,
                "scheduled_tasks_timeout": 300}

    def _init_app(self, app, state):
        if not app.config.get('RQ_REDIS_URL') and has_extension('frasco_redis', app):
            app.config['RQ_REDIS_URL'] = app.extensions.frasco_redis.options['url']

        app.config.setdefault('RQ_JOB_CLASS', 'frasco.tasks.job.FrascoJob')
        if app.testing:
            app.config.setdefault('RQ_ASYNC', False)
        state.rq = RQ(app, default_timeout=state.options['tasks_timeout'])
        state.rq.exception_handler(per_task_exception_handler)


def per_task_exception_handler(job, *exc_info):
    if hasattr(job.func, '__task_exception_handler__'):
        return job.func.__task_exception_handler__(job, *exc_info)


def enqueue_task_now(func, *args, **kwargs):
    return enqueue_now(func, args=args, kwargs=kwargs)


def enqueue_now(func, **options):
    if getattr(func, '__task_options__', None):
        options.update(func.__task_options__)
    queue_name = options.pop('queue', None)
    if callable(queue_name):
        queue_name = queue_name()
    return get_extension_state('frasco_tasks').rq.get_queue(queue_name).enqueue_call(func, **options)


def enqueue_task(func, *args, **kwargs):
    return enqueue(func, args=args, kwargs=kwargs)


@delayed_tx_calls.proxy
def enqueue(func, **options):
    return enqueue_now(func, **options)


def get_enqueued_job(id):
    state = get_extension_state('frasco_tasks')
    return FrascoJob.fetch(id, connection=state.rq.connection)


def task(**options):
    def wrapper(func):
        func.__task_options__ = options
        setattr(func, 'enqueue', functools.partial(enqueue_task, func))
        setattr(func, 'enqueue_now', functools.partial(enqueue_task_now, func))
        setattr(func, 'exception_handler', task_exception_handler(func))
        setattr(func, 'timeout_handler', task_exception_handler(func, JobTimeoutException))
        return func
    return wrapper


def task_exception_handler(task_func, exc_type=None):
    def decorator(handler_func):
        task_func.__task_exception_handler__ = _wrap_exc_handler_for_type(handler_func, exc_type) if exc_type else handler_func
        return handler_func
    return decorator


def _wrap_exc_handler_for_type(handler_func, exc_type):
    @functools.wraps(handler_func)
    def wrapper(job, *exc_info):
        if exc_info[0] is exc_type:
            return handler_func(job, *exc_info)
    return wrapper


def schedule_task(pattern, import_name_or_func):
    state = get_extension_state('frasco_tasks')
    if isinstance(import_name_or_func, str):
        func = import_string(import_name_or_func)
        import_name = import_name_or_func
    else:
        func = import_name_or_func
        import_name = "%s.%s" % (func.__module__, func.__name__)
    try:
        logger.info("Scheduling task %s at %s" % (import_name, pattern))
        return state.rq.get_scheduler().cron(pattern, func,
            id="cron-%s" % import_name.replace('.', '-'),
            timeout=state.options['scheduled_tasks_timeout'])
    except redis.exceptions.ConnectionError:
        logger.error("Cannot initialize scheduled tasks as no redis connection is available")


def clear_all_scheduled_tasks():
    scheduler = get_extension_state('frasco_tasks').rq.get_scheduler()
    for job in scheduler.get_jobs():
        scheduler.cancel(job)


_rq2_scheduler = cli.scheduler

@functools.wraps(_rq2_scheduler)
def _scheduler(*args, **kwargs):
    state = get_extension_state('frasco_tasks')
    clear_all_scheduled_tasks()
    for import_name, pattern in state.options.get('schedule', {}).items():
        schedule_task(pattern, import_name)
    _rq2_scheduler(*args, **kwargs)

cli._commands['scheduler'] = _scheduler
