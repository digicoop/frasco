from . import enqueue_now, enqueue_task, enqueue_task_now, get_enqueued_job, logger
from .job import FrascoJob
from rq import get_current_job
from frasco.ext import get_extension_state
from contextlib import contextmanager
import uuid


def connect_as_background_task(signal, **kwargs):
    def decorator(func):
        kwargs['weak'] = False
        def listener(sender, **kwargs):
            enqueue_task(func, sender, **kwargs)
        signal.connect(listener, **kwargs)
        return func
    return decorator


def _parallel_tasks_callback(identifier, job_id, callback, args, kwargs):
    redis = get_extension_state('frasco_tasks').rq.connection
    remaining_jobs = redis.scard(identifier)
    remaining_jobs -= redis.srem(identifier, job_id)
    if remaining_jobs > 0:
        return
    redis.delete(identifier)
    callback(*args, **kwargs)


@contextmanager
def parallel_tasks_callback(callback, *callback_args, identifier=None, **callback_kwargs):
    redis = get_extension_state('frasco_tasks').rq.connection
    if not identifier:
        identifier = str(uuid.uuid4())

    def enqueue(*args, **kwargs):
        job = enqueue_task_now(*args, **kwargs)
        redis.sadd(identifier, job.id)
        return enqueue_now(_parallel_tasks_callback, args=(identifier, job.id, callback, callback_args, callback_kwargs), depends_on=job)

    yield enqueue


def cancel_parallel_tasks(identifier, delete=True):
    redis = get_extension_state('frasco_tasks').rq.connection
    job_ids = redis.smembers(identifier)
    if not job_ids:
        return
    jobs = FrascoJob.fetch_many([i.decode('utf-8') for i in job_ids], connection=redis)
    logger.debug("Cancelling %s parallel tasks identified by %s" % (len(jobs), identifier))
    for job in jobs:
        if delete:
            job.delete(delete_dependents=True)
        elif not job.ended_at:
            job.cancel()
    redis.delete(identifier)
    return jobs
