import gzip
import hashlib
import json
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse


class GzipRequestMiddleware:
    def __init__(self, app, max_bytes: int = 25 * 1024 * 1024): self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http": return await self.app(scope, receive, send)
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        if headers.get(b"content-encoding", b"").lower() != b"gzip": return await self.app(scope, receive, send)
        body = bytearray(); more = True
        while more:
            message = await receive(); body.extend(message.get("body", b"")); more = message.get("more_body", False)
            if len(body) > self.max_bytes:
                response = JSONResponse({"type": "about:blank", "title": "Payload Too Large", "status": 413, "detail": "Compressed request is too large"}, status_code=413, media_type="application/problem+json")
                return await response(scope, receive, send)
        try: decoded = gzip.decompress(bytes(body))
        except (gzip.BadGzipFile, EOFError):
            response = JSONResponse({"type": "about:blank", "title": "Bad Request", "status": 400, "detail": "Invalid gzip body"}, status_code=400, media_type="application/problem+json")
            return await response(scope, receive, send)
        if len(decoded) > self.max_bytes:
            response = JSONResponse({"type": "about:blank", "title": "Payload Too Large", "status": 413, "detail": "Decompressed request is too large"}, status_code=413, media_type="application/problem+json")
            return await response(scope, receive, send)
        scope["headers"] = [(key, value) for key, value in scope["headers"] if key.lower() not in {b"content-encoding", b"content-length"}] + [(b"content-length", str(len(decoded)).encode())]
        delivered = False
        async def decoded_receive():
            nonlocal delivered
            if delivered: return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True; return {"type": "http.request", "body": decoded, "more_body": False}
        await self.app(scope, decoded_receive, send)


async def protection_middleware(request: Request, call_next, redis_provider):
    path = request.url.path
    if path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"} and not request.headers.get("authorization"):
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.netloc != request.headers.get("host"):
                return JSONResponse({"type": "about:blank", "title": "Forbidden", "status": 403, "detail": "Cross-site request rejected"}, status_code=403, media_type="application/problem+json")
    client_key = request.headers.get("authorization") or request.cookies.get("wm_access") or (request.client.host if request.client else "unknown")
    is_agent = path.startswith("/api/v1/agent/")
    limit = 60 if is_agent else 300
    redis = redis_provider()
    if redis is not None and path.startswith("/api/"):
        fingerprint = hashlib.sha256(client_key.encode()).hexdigest()[:32]
        key = f"rate:{'agent' if is_agent else 'web'}:{fingerprint}"
        count = await redis.incr(key)
        if count == 1: await redis.expire(key, 60)
        if count > limit:
            return JSONResponse({"type": "about:blank", "title": "Too Many Requests", "status": 429, "detail": "Rate limit exceeded"}, status_code=429, headers={"Retry-After": "60"}, media_type="application/problem+json")
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; media-src 'self' blob:; frame-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' ws: wss:")
    return response
