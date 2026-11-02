"""In-memory publish and subscribe for Server-Sent Events."""
import json
import queue
import threading

HEARTBEAT_SECONDS = 15


class Broker:
    def __init__(self):
        self._channels = {}
        self._lock = threading.Lock()

    def subscribe(self, channel):
        q = queue.Queue(maxsize=100)
        with self._lock:
            self._channels.setdefault(channel, set()).add(q)
        return q

    def unsubscribe(self, channel, q):
        with self._lock:
            subscribers = self._channels.get(channel)
            if subscribers:
                subscribers.discard(q)

    def publish(self, channel, event, data=None):
        message = f"event: {event}\ndata: {json.dumps(data or {})}\n\n"
        with self._lock:
            subscribers = list(self._channels.get(channel, ()))
        for q in subscribers:
            try:
                q.put_nowait(message)
            except queue.Full:
                pass  # A stalled browser reloads its state when it reconnects.

    def stream(self, channel):
        q = self.subscribe(channel)

        def generate():
            try:
                yield ": connected\n\n"
                while True:
                    try:
                        yield q.get(timeout=HEARTBEAT_SECONDS)
                    except queue.Empty:
                        yield ": ping\n\n"
            finally:
                self.unsubscribe(channel, q)

        return generate()
