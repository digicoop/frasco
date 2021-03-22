from . import enqueue_task


def connect_as_background_task(signal, **kwargs):
    def decorator(func):
        kwargs['weak'] = False
        @signal.connect(**kwargs)
        def listener(sender, **kwargs):
            enqueue_task(func, sender, **kwargs)
        return func
    return decorator
