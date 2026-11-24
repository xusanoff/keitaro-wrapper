import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

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
    # 4xx from Keitaro = it rejected our data; anything else = upstream problem.
    code = 422 if exc.status_code and 400 <= exc.status_code < 500 and exc.status_code != 401 else 502
    msg = f"Keitaro rejected the request: {exc.message}" if code == 422 else str(exc)
    if exc.status_code == 401:
        msg = "Keitaro rejected the API key. Check KEITARO_API_KEY in .env."
    return JSONResponse({"detail": msg}, status_code=code)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    parts = [f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors()]
    return JSONResponse({"detail": "; ".join(parts) or "Invalid request"}, status_code=422)


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}
