from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from daran_proxy_stack.web import api as _api

_HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(_HERE / "templates"))

app = FastAPI(title="Daran Proxy Stack Panel", docs_url="/api/docs", redoc_url=None)
app.include_router(_api.router, prefix="/api/v1")

_VIEWS = ["overview", "servers", "mtproxy", "warp", "jobs"]


@app.get("/", response_class=RedirectResponse, include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse("/overview")


def _view(name: str):
    async def handler(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(f"{name}.html", {"request": request, "active": name, "views": _VIEWS})
    handler.__name__ = name
    return handler


for _v in _VIEWS:
    app.add_api_route(f"/{_v}", _view(_v), response_class=HTMLResponse, include_in_schema=False)
