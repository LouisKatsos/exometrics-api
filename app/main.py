from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import connect_db, close_db
from app.routers import auth, metrics

app = FastAPI(title='ExoMetrics API', version='0.1.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(auth.router)
app.include_router(metrics.router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    body = await request.body()
    body_str = body.decode('utf-8', errors='replace')
    print(f'[VALIDATION] content-type={request.headers.get("content-type")} body={body_str[:400]}', flush=True)
    return JSONResponse(
        status_code=422,
        content={
            'detail': exc.errors(),
            'body_received': body_str[:400],
            'content_type': request.headers.get('content-type'),
        },
    )


@app.on_event('startup')
async def startup():
    await connect_db()


@app.on_event('shutdown')
async def shutdown():
    await close_db()


@app.get('/health')
def health():
    return {'status': 'ok'}
