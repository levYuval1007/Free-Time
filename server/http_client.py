import http.client
import queue


class TransportError(Exception):
    pass


class PooledClient:
    # Keep-alive HTTPS connections shared across threads; the server spawns a thread per request,
    # so a thread-local connection would never be reused.
    def __init__(self, host, timeout=20, pool_size=8):
        self.host = host
        self.timeout = timeout
        self._pool = queue.LifoQueue(maxsize=pool_size)

    def _new(self):
        return http.client.HTTPSConnection(self.host, timeout=self.timeout)

    def request(self, method, path, body=None, headers=None):
        for attempt in (1, 2):
            try:
                conn = self._pool.get_nowait() if attempt == 1 else self._new()
            except queue.Empty:
                conn = self._new()
            try:
                conn.request(method, path, body=body, headers=headers or {})
                resp = conn.getresponse()
                raw = resp.read()
            except (http.client.HTTPException, OSError) as err:
                conn.close()
                if attempt == 2:
                    raise TransportError(str(err))
                continue
            try:
                self._pool.put_nowait(conn)
            except queue.Full:
                conn.close()
            return resp.status, raw
