import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")  # must run before app imports

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.api.analyze import router as analyze_router  # noqa: E402
from app.api.macro import router as macro_router  # noqa: E402
from app.api.news import router as news_router  # noqa: E402
from app.api.portfolio import router as portfolio_router  # noqa: E402
from app.api.screen import router as screen_router  # noqa: E402

app = FastAPI(title="StockScope API", version="0.1.0")

import os  # noqa: E402

_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
# Allow additional origins from env, e.g. ALLOWED_ORIGINS=https://my-app.vercel.app
_extra = os.environ.get("ALLOWED_ORIGINS", "")
for _o in _extra.split(","):
    _o = _o.strip()
    if _o:
        _ALLOWED_ORIGINS.append(_o)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze_router)
app.include_router(portfolio_router)
app.include_router(screen_router)
app.include_router(macro_router)
app.include_router(news_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
