"""Dashboard de Rechazos Comerciales — Misiones. API FastAPI."""
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import comentarios, mapeo, mensual, rechazos, sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="Rechazos Comerciales — Misiones",
    description="Tablero de rechazos de productos (Chess + GESCOM) para la matinal de ventas.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list(),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return resp


@app.exception_handler(Exception)
async def on_error(request: Request, exc: Exception):
    logging.getLogger("api").exception("Error no controlado en %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": str(exc)})


@app.get("/api/health")
def health():
    return {"ok": True, "service": "rechazos-misiones"}


app.include_router(rechazos.router)
app.include_router(mensual.router)
app.include_router(sync.router)
app.include_router(mapeo.router)
app.include_router(comentarios.router)
