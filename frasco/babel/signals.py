from flask.signals import Namespace


_signals = Namespace()
translation_extracted = _signals.signal("translation_extracted")
translation_updated = _signals.signal("translation_updated")
translation_compiled = _signals.signal("translation_compiled")
