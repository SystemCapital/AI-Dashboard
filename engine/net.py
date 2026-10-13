"""
One GET for every collector, with a short retry when the connection drops.

A read that fails on a transient fault (the TLS stream cut off mid-handshake, a connection reset, a server answering
429 / 502 / 503 / 504) is tried up to twice more, a few seconds apart, before the collector treats it as a failure and
keeps its last good data. Anything else fails at once: a 403 or 404, a timeout (already a long wait), a refused proxy
tunnel, a certificate error, or a miss in tools/run_cached.py's browser cache. A gzip body is unpacked: some servers
(InferenceX's API since 2026-10-14) send one even though the request asks for no compression. Standard library only.
"""
import gzip, time, socket, ssl, http.client, urllib.request, urllib.error

RETRY_DELAYS = (3, 8)                     # seconds before the second and third attempts
RETRY_HTTP = {429, 502, 503, 504}


def transient(ex):
    if isinstance(ex, urllib.error.HTTPError):
        return ex.code in RETRY_HTTP
    if isinstance(ex, urllib.error.URLError):
        ex = ex.reason
    if isinstance(ex, (ssl.SSLCertVerificationError, socket.timeout, TimeoutError)):
        return False
    return isinstance(ex, (ssl.SSLError, ConnectionError, http.client.RemoteDisconnected, http.client.IncompleteRead))


def read(req, timeout=60):
    """urllib.request.urlopen(req).read(), retried on a transient fault; returns the body as bytes, gzip unpacked"""
    for delay in RETRY_DELAYS + (None,):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                headers = getattr(r, "headers", None)
                encoding = ((headers.get("Content-Encoding") if headers is not None else None) or "").lower()
            break
        except Exception as ex:
            if delay is None or not transient(ex):
                raise
            time.sleep(delay)
    if encoding == "gzip" or body[:2] == b"\x1f\x8b":
        try:
            body = gzip.decompress(body)
        except OSError:
            pass
    return body
