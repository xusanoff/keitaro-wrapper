import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from app.api.routes import router as api_router
from app.keitaro.client import KeitaroError
from app.services.errors import ServiceError
from app.web.pages import router as web_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Keitaro Wrapper", version="1.0.0")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static")
app.include_router(api_router)
app.include_router(web_router)


@app.exception_handler(ServiceError)
async def service_error(_: Request, exc: ServiceError):
    return JSONResponse({"detail": exc.message}, status_code=exc.status_code)


@app.exception_handler(KeitaroError)
async def keitaro_error(_: Request, exc: KeitaroError):
    status = exc.status_code
    if status in (401, 403):
        code, msg = 502, "Keitaro rejected the API key. Check KEITARO_API_KEY in .env."
    elif status == 404:
        code, msg = 404, "Keitaro could not find it (it may have been deleted). Press Fetch streams to reload."
    elif status == 429:
        code, msg = 503, "Keitaro is rate-limiting requests. Wait a few seconds and try again."
    elif status and 400 <= status < 500:
        code, msg = 422, f"Keitaro rejected the request: {exc.message}"
    elif status:
        code, msg = 502, f"Keitaro failed with error {status}. Try again in a moment."
    else:
        code, msg = 502, f"{exc.message}. Check KEITARO_URL and your connection."
    return JSONResponse({"detail": msg}, status_code=code)


@app.exception_handler(IntegrityError)
async def integrity_error(_: Request, exc: IntegrityError):
    # e.g. the same offer added twice by a double click / two tabs
    return JSONResponse(
        {"detail": "This change conflicts with another one made at the same time. Reload and try again."},
        status_code=409,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    parts = [f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors()]
    return JSONResponse({"detail": "; ".join(parts) or "Invalid request"}, status_code=422)


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}
