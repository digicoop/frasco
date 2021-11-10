from flask import has_app_context, current_app, has_request_context, session, request
from frasco.users import user_login_context, is_user_logged_in, current_user
from frasco.utils import import_string
from frasco.ctx import ContextStack, DelayedCallsContext
from flask_rq2.job import FlaskJob
from rq.job import UNEVALUATED, dumps, Job as RQJob
from contextlib import contextmanager


prevent_circular_task_ctx = ContextStack()
synchronous_tasks = DelayedCallsContext()


@contextmanager
def prevent_circular_task(ctx_id):
    exists = ctx_id in prevent_circular_task_ctx.stack
    with prevent_circular_task_ctx(ctx_id):
        yield exists


def pack_job_args(data):
    """Traverse data and converts every object with a __taskdump__() method
    """
    if hasattr(data, "__taskdump__"):
        cls, state = data.__taskdump__()
        if not cls:
            cls = data.__class__.__module__ + "." + data.__class__.__name__
        return {"$taskobj": [cls, state]}
    if isinstance(data, (list, tuple)):
        lst = []
        for item in data:
            lst.append(pack_job_args(item))
        return lst
    if isinstance(data, dict):
        dct = {}
        for k, v in data.items():
            dct[k] = pack_job_args(v)
        return dct
    return data


def unpack_job_args(data):
    """Traverse data and transforms back objects which where dumped
    using __taskdump()
    """
    if isinstance(data, (list, tuple)):
        lst = []
        for item in data:
            lst.append(unpack_job_args(item))
        return lst
    if isinstance(data, dict):
        if "$taskobj" in data:
            cls = import_string(data["$taskobj"][0])
            return cls.__taskload__(data["$taskobj"][1])
        else:
            dct = {}
            for k, v in data.items():
                dct[k] = unpack_job_args(v)
            return dct
    return data


class FrascoJob(FlaskJob):
    @classmethod
    def create(cls, func, *args, **kwargs):
        job = super(FrascoJob, cls).create(func, *args, **kwargs)
        job.meta.setdefault('forwarded_contexts', {})['frasco.tasks.job.prevent_circular_task_ctx'] = prevent_circular_task_ctx.stack
        if is_user_logged_in():
            job.meta['current_user_id'] = current_user.id
        if has_request_context():
            job.meta.update({
                'endpoint': request.endpoint,
                'remote_addr': request.remote_addr,
                'session': dict(session)
            })
        return job

    @property
    def data(self):
        if self._data is UNEVALUATED:
            if self._func_name is UNEVALUATED:
                raise ValueError('Cannot build the job data')

            if self._instance is UNEVALUATED:
                self._instance = None

            if self._args is UNEVALUATED:
                args = ()
            else:
                args = pack_job_args(self._args)

            if self._kwargs is UNEVALUATED:
                kwargs = {}
            else:
                kwargs = pack_job_args(self._kwargs)

            job_tuple = self._func_name, self._instance, args, kwargs
            self._data = dumps(job_tuple)
        return self._data

    @data.setter
    def data(self, value):
        self._data = value
        self._func_name = UNEVALUATED
        self._instance = UNEVALUATED
        self._args = UNEVALUATED
        self._kwargs = UNEVALUATED

    def perform(self):
        app = self.load_app()
        if synchronous_tasks.calling_ctx.top or not app.config.get('RQ_ASYNC'):
            return self.perform_in_app_context(True)
        with app.app_context():
            rv = self.perform_in_app_context()
        return rv

    def perform_in_app_context(self, is_sync=False):
        clear_extended_fowarded_contexts = {}
        if not is_sync and self.meta.get('forwarded_contexts'):
            for ctx_import_str, stack in self.meta['forwarded_contexts'].items():
                import_string(ctx_import_str).stack.extend(stack)
                clear_extended_fowarded_contexts[ctx_import_str] = len(stack) # keep track using temp variable as if it runs in sync mode, stack will be modified
        try:
            current_user_id = self.meta.get('current_user_id')
            if current_user_id and not is_user_logged_in(): # user is already logged in if task is async=False
                with user_login_context(current_app.extensions.frasco_users.Model.query.get(current_user_id)):
                    rv = RQJob.perform(self)
            else:
                rv = RQJob.perform(self)
        finally:
            if clear_extended_fowarded_contexts:
                for ctx_import_str, clear_len in clear_extended_fowarded_contexts.items():
                    del import_string(ctx_import_str).stack[-clear_len:]
        return rv

    def _execute(self):
        return self.func(*unpack_job_args(self.args), **unpack_job_args(self.kwargs))
