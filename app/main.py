import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import database, dependencies
from app.config import settings
from app.middleware import (
    AccessLogMiddleware,
    BodySizeLimitMiddleware,
    IpRateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.records import sanitize_errors
from app.routers import auth, metrics

logging.basicConfig(
    level=settings.log_level.upper(),
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)
logger = logging.getLogger('exometrics')


@asynccontextmanager
async def lifespan(app: FastAPI):
    dependencies.init_firebase()
    await database.connect_db()
    await database.ensure_indexes()
    logger.info('ExoMetrics API started (environment=%s, docs=%s)', settings.environment, settings.docs_enabled)
    yield
    await database.close_db()


def create_app() -> FastAPI:
    docs = settings.docs_enabled
    app = FastAPI(
        title='ExoMetrics API',
        version='0.2.0',
        lifespan=lifespan,
        docs_url='/docs' if docs else None,
        redoc_url='/redoc' if docs else None,
        openapi_url='/openapi.json' if docs else None,
    )

    # Added innermost first: requests pass access log -> security headers ->
    # per-IP flood guard -> CORS -> body size limit -> routes.
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # The API uses bearer tokens, never cookies, so browsers are never
        # allowed to send credentials cross-origin.
        allow_credentials=False,
        allow_methods=['GET', 'POST', 'PATCH'],
        allow_headers=['Authorization', 'Content-Type'],
    )
    app.add_middleware(IpRateLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(AccessLogMiddleware)

    app.include_router(auth.router)
    app.include_router(metrics.router)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        # Same 422 and `detail` list as before, but without echoing the body
        # or the submitted values: they are health data.
        return JSONResponse(status_code=422, content={'detail': sanitize_errors(exc.errors())})

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.exception('Unhandled error on %s %s', request.method, request.url.path)
        return JSONResponse(status_code=500, content={'detail': 'Internal server error'})

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.get('/health/ready')
    async def ready():
        if await database.ping():
            return {'status': 'ok'}
        return JSONResponse(status_code=503, content={'status': 'unavailable'})

    return app


app = create_app()
