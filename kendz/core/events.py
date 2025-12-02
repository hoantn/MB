# kendz/core/events.py
from collections import defaultdict

class EventBus:
    def __init__(self):
        self._subs = defaultdict(list)

    def subscribe(self, event, handler):
        self._subs[event].append(handler)

    def publish(self, event, payload):
        for h in self._subs[event]:
            h(payload)
