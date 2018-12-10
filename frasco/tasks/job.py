from flask import has_app_context, current_app, has_request_context, session, request
from frasco.users import user_login_context, is_user_logged_in, current_user
from frasco.utils import import_string
from flask_rq2.job import FlaskJob
from rq.job import unpickle, UNEVALUATED, dumps, Job as RQJob


def pack_task_args(data):
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
            lst.append(pack_task_args(item))
        return lst
    if isinstance(data, dict):
        dct = {}
        for k, v in data.iteritems():
            dct[k] = pack_task_args(v)
        return dct
    return data


def unpack_task_args(data):
    """Traverse data and transforms back objects which where dumped
    using __taskdump()
    """
    if isinstance(data, (list, tuple)):
        lst = []
        for item in data:
            lst.append(unpack_task_args(item))
        return lst
    if isinstance(data, dict):
        if "$taskobj" in data:
            cls = import_string(data["$taskobj"][0])
            return cls.__taskload__(data["$taskobj"][1])
        else:
            dct = {}
            for k, v in data.iteritems():
                dct[k] = unpack_task_args(v)
            return dct
    return data


class FrascoJob(FlaskJob):
    @classmethod
    def create(cls, func, *args, **kwargs):
        job = super(FrascoJob, cls).create(func, *args, **kwargs)
        if is_user_logged_in():
            job.meta['current_user_id'] = current_user.id
        if has_request_context():
            job.meta.update({
                'endpoint': request.endpoint,
                'remote_addr': request.remote_addr,
                'session': dict(session)
            })
        return job

    def _unpickle_data(self):
        self._func_name, self._instance, self._args, self._kwargs = unpickle(self.data)
        self._args = unpack_task_args(self._args)
        self._kwargs = unpack_task_args(self._kwargs)

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
                args = pack_task_args(self._args)

            if self._kwargs is UNEVALUATED:
                kwargs = {}
            else:
                kwargs = pack_task_args(self._kwargs)

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
        if has_app_context():
            # if async=False, app context may already exist
            return self.perform_in_app_context()
        app = self.load_app()
        with app.app_context():
            return self.perform_in_app_context()

    def perform_in_app_context(self):
        current_user_id = self.meta.get('current_user_id')
        if current_user_id and not is_user_logged_in(): # user is already logged in if task is async=False
            with user_login_context(current_app.extensions.frasco_users.Model.query.get(current_user_id)):
                return RQJob.perform(self)
        else:
            return RQJob.perform(self)
