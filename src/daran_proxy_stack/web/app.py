from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from daran_proxy_stack.web import api as _api
from daran_proxy_stack.web.auth import AuthManager

_HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(_HERE / "templates"))

# Config dir: look for project-level artifacts, fall back to /opt/...
def _find_config_dir() -> Path:
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "artifacts").exists():
            return p / "artifacts" / "generated"
    return Path("/opt/daran-proxy-stack/artifacts/generated")


_auth = AuthManager(_find_config_dir())

app = FastAPI(title="Daran Proxy Stack Panel", docs_url="/api/docs", redoc_url=None)
app.include_router(_api.router, prefix="/api/v1")

_VIEWS = ["overview", "servers", "mtproxy", "warp", "cascade", "amneziawg", "jobs", "inventory"]

_COOKIE_NAME = "daran_token"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _get_token_from_request(request: Request) -> str | None:
    return request.cookies.get(_COOKIE_NAME)


def _require_auth(request: Request) -> dict:
    """FastAPI dependency — redirect to login if not authenticated."""
    token = _get_token_from_request(request)
    if token:
        payload = _auth.verify_token(token)
        if payload:
            return payload
    # Store destination for post-login redirect
    dest = request.url.path
    raise HTTPException(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": f"/login?next={dest}"},
    )


AuthDep = Annotated[dict, Depends(_require_auth)]


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request, next: str = "/") -> HTMLResponse:
    # If already logged in, redirect
    token = _get_token_from_request(request)
    if token and _auth.verify_token(token):
        return RedirectResponse(next or "/")
    # If no credentials set up yet, redirect to setup
    if not _auth.has_credentials():
        return RedirectResponse("/setup")
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"request": request, "next": next, "error": None},
    )


@app.post("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/"),
) -> HTMLResponse:
    if _auth.authenticate(username, password):
        token = _auth.create_token(username)
        response = RedirectResponse(next or "/", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            key=_COOKIE_NAME,
            value=token,
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 7,  # 7 days
        )
        return response
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"request": request, "next": next, "error": "Неверный логин или пароль"},
        status_code=status.HTTP_401_UNAUTHORIZED,
    )


@app.get("/logout", include_in_schema=False)
async def logout() -> RedirectResponse:
    response = RedirectResponse("/login")
    response.delete_cookie(_COOKIE_NAME)
    return response


@app.get("/setup", response_class=HTMLResponse, include_in_schema=False)
async def setup_page(request: Request) -> HTMLResponse:
    # If credentials already exist, require auth to change password
    if _auth.has_credentials():
        token = _get_token_from_request(request)
        if not token or not _auth.verify_token(token):
            return RedirectResponse("/login?next=/setup")
    return templates.TemplateResponse(
        request=request,
        name="setup.html",
        context={"request": request, "error": None, "existing": _auth.has_credentials()},
    )


@app.post("/setup", response_class=HTMLResponse, include_in_schema=False)
async def setup_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
) -> HTMLResponse:
    errors = []
    if len(username) < 3:
        errors.append("Имя пользователя минимум 3 символа")
    if len(password) < 8:
        errors.append("Пароль минимум 8 символов")
    if password != password2:
        errors.append("Пароли не совпадают")
    if errors:
        return templates.TemplateResponse(
            request=request,
            name="setup.html",
            context={"request": request, "error": "; ".join(errors), "existing": _auth.has_credentials()},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    _auth.save_credentials(username, password)
    # Auto-login after setup
    token = _auth.create_token(username)
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
    )
    return response


# ---------------------------------------------------------------------------
# Protected view routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=RedirectResponse, include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse("/overview")


def _protected_view(name: str):
    async def handler(request: Request, _user: AuthDep) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name=f"{name}.html",
            context={"request": request, "active": name, "views": _VIEWS, "user": _user},
        )
    handler.__name__ = name
    return handler


for _v in _VIEWS:
    app.add_api_route(
        f"/{_v}",
        _protected_view(_v),
        response_class=HTMLResponse,
        include_in_schema=False,
    )
