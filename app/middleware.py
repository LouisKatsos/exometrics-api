"""Plain ASGI middleware (no BaseHTTPMiddleware, so streaming stays intact)."""
import logging
import time
import uuid

from fastapi import HTTPException
from starlette.responses import JSONResponse

from app.config import settings
from app.ratelimit import RateLimiter

access_logger = logging.getLogger('exometrics.access')

SECURITY_HEADERS = [
    (b'x-content-type-options', b'nosniff'),
    (b'x-frame-options', b'DENY'),
    (b'referrer-policy', b'no-referrer'),
    (b'cache-control', b'no-store'),
    # The legacy browser XSS filter is itself exploitable; current guidance is to turn it off.
    (b'x-xss-protection', b'0'),
    (b'cross-origin-opener-policy', b'same-origin'),
    (b'cross-origin-resource-policy', b'same-origin'),
    (b'permissions-policy', b'camera=(), microphone=(), geolocation=(), payment=()'),
]

# JSON responses never need scripts, styles or frames. The interactive docs
# pages do (they load Swagger/ReDoc), so they are left out.
API_CSP = (b'content-security-policy', b"default-src 'none'; frame-ancestors 'none'")
DOCS_PATHS = ('/docs', '/redoc')

# Only in production: tells clients to use HTTPS for this host for a year.
# Render terminates TLS, so every real request already arrives over HTTPS.
HSTS = (b'strict-transport-security', b'max-age=31536000; includeSubDomains')


class BodyTooLarge(HTTPException):
    """An HTTPException so FastAPI passes it through unchanged while reading the body."""

    def __init__(self):
        super().__init__(status_code=413, detail='Request body too large')


class BodySizeLimitMiddleware:
    """Rejects bodies over settings.max_body_bytes with 413.

    Checks Content-Length up front, and also counts the bytes actually
    received so a chunked upload can't get around the limit.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        limit = settings.max_body_bytes
        if scope['type'] != 'http' or limit <= 0:
            await self.app(scope, receive, send)
            return

        for name, value in scope.get('headers') or []:
            if name == b'content-length':
                try:
                    too_large = int(value) > limit
                except ValueError:
                    too_large = False
                if too_large:
                    await JSONResponse(status_code=413, content={'detail': 'Request body too large'})(scope, receive, send)
                    return

        received = 0
        response_started = False

        async def counting_receive():
            nonlocal received
            message = await receive()
            if message['type'] == 'http.request':
                received += len(message.get('body', b''))
                if received > limit:
                    raise BodyTooLarge()
            return message

        async def tracking_send(message):
            nonlocal response_started
            if message['type'] == 'http.response.start':
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except BodyTooLarge:
            if response_started:
                raise
            await JSONResponse(status_code=413, content={'detail': 'Request body too large'})(scope, receive, send)


def client_ip(scope) -> str:
    """The caller's IP. Behind Render's proxy the socket peer is the proxy,
    so the first X-Forwarded-For entry is used when present."""
    for name, value in scope.get('headers') or []:
        if name == b'x-forwarded-for':
            first = value.decode('latin-1').split(',')[0].strip()
            if first:
                return first[:64]
    client = scope.get('client')
    return client[0] if client else 'unknown'


class IpRateLimitMiddleware:
    """Coarse per-IP flood guard for every request, before authentication.

    The real per-user limit lives in the auth dependency. This one is set
    high (settings.ip_rate_limit_per_minute) because several study phones
    can share one network address. X-Forwarded-For can be forged, so this
    slows floods down rather than identifying anyone.
    """

    def __init__(self, app):
        self.app = app
        self.limiter = RateLimiter()

    async def __call__(self, scope, receive, send):
        limit = settings.ip_rate_limit_per_minute
        if scope['type'] != 'http' or limit <= 0:
            await self.app(scope, receive, send)
            return
        retry_after = self.limiter.hit(client_ip(scope), limit)
        if retry_after is not None:
            response = JSONResponse(
                status_code=429,
                content={'detail': 'Too many requests'},
                headers={'Retry-After': str(retry_after)},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        extra = list(SECURITY_HEADERS)
        if not scope.get('path', '').startswith(DOCS_PATHS):
            extra.append(API_CSP)
        if settings.is_production:
            extra.append(HSTS)

        async def send_with_headers(message):
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers') or [])
                present = {name.lower() for name, _ in headers}
                headers.extend(h for h in extra if h[0] not in present)
                message['headers'] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class AccessLogMiddleware:
    """One line per request: method, path, status, duration and a request id.

    Never logs bodies, headers or query strings (they can carry tokens or
    health data). The request id is returned as X-Request-ID.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        request_id = None
        for name, value in scope.get('headers') or []:
            if name == b'x-request-id':
                candidate = value.decode('latin-1')[:64]
                if candidate.replace('-', '').isalnum():
                    request_id = candidate
                break
        request_id = request_id or uuid.uuid4().hex
        start = time.perf_counter()
        status = 500

        async def send_with_id(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                headers = list(message.get('headers') or [])
                headers.append((b'x-request-id', request_id.encode('latin-1')))
                message['headers'] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            access_logger.info(
                '%s %s %s %.1fms id=%s',
                scope.get('method'), scope.get('path'), status,
                (time.perf_counter() - start) * 1000, request_id,
            )
