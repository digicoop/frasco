from blinker import signal
from . import emit_push_event, emit_user_push_event
from ..utils import unknown_value


exposed_signals = {}
exposed_signal_emitted = signal('exposed_signal_emitted')


def expose_signal(signal, marshaller=None, filter=None, room_getter=None, push_event_name=None, **kwargs):
    if not push_event_name:
        push_event_name = signal.name

    def marshal(sender, **kw):
        if marshaller:
            return marshaller(sender, **kw)
        return kw or None

    def emit(sender, **kw):
        emit_kwargs = dict(kwargs)
        if '_push_skip_self' in kw:
            emit_kwargs['skip_self'] = kw.pop('_push_skip_self')
        data = marshal(sender, **kw)
        if room_getter:
            room, is_user = room_getter(sender)
        else:
            room, is_user = getattr(sender, 'exposed_signal_room', (None, False))
        if is_user:
            emit_user_push_event(room, push_event_name, data, **emit_kwargs)
        else:
            emit_push_event(push_event_name, data, room=room, **emit_kwargs)
        return data

    def listener(sender, **kw):
        skip_expose = kw.pop('_skip_expose', False)
        skip_push = kw.pop('_skip_push', skip_expose)
        skip_self =  kw.pop('_push_skip_self', True)
        if filter and not filter(sender, **kw):
            return
        push_data = unknown_value
        if not skip_push:
            push_data = emit(sender, _push_skip_self=skip_self, **kw)
        if not skip_expose:
            if push_data is unknown_value:
                push_data = marshal(sender, **kw)
            exposed_signal_emitted.send(sender, signal_name=signal.name, signal_data=kw, push_data=push_data)

    listener.marshal = marshal
    listener.emit = emit
    listener.filter = filter
    signal.exposed = listener
    exposed_signals[signal] = listener # we make sure the reference to listener is kept so we don't use a weak listener
    signal.connect(listener)
    return signal


def exposed_signal(name, **kwargs):
    return expose_signal(signal(name, doc=kwargs.pop('doc', None)), **kwargs)
