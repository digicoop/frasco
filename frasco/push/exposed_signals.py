from blinker import signal
from . import emit_push_event, emit_user_push_event


exposed_signals = {}
exposed_signal_emitted = signal('exposed_signal_emitted')


def expose_signal(signal, marshaller=None, room_getter=None, push_event_name=None, **kwargs):
    def listener(sender, **kw):
        if marshaller:
            data = marshaller(sender, **kw)
        else:
            data = kw or None
        if room_getter:
            room = room_getter(sender)
        else:
            room = getattr(sender, 'exposed_signal_room', None)
        emit_kwargs = dict(kwargs)
        if '_push_skip_self' in kw:
            emit_kwargs['skip_self'] = kw.pop('_push_skip_self')
        if room:
            emit_push_event(push_event_name or signal.name, data, room=room, **emit_kwargs)
        else:
            emit_user_push_event(push_event_name or signal.name, data, **emit_kwargs)
        exposed_signal_emitted.send(sender, signal_name=signal.name, signal_data=kw, push_data=data)

    listener.marshaller = marshaller
    exposed_signals[signal] = listener # we make sure the reference to listener is kept so we don't use a weak listener
    signal.connect(listener)
    signal.exposed = listener
    return signal


def exposed_signal(name, **kwargs):
    return expose_signal(signal(name, doc=kwargs.pop('doc', None)), **kwargs)
