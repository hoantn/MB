# kendz/core/errors.py
class KendzError(Exception): pass
class ConfigError(KendzError): pass
class VisionError(KendzError): pass
class EngineError(KendzError): pass
class AutomationError(KendzError): pass
