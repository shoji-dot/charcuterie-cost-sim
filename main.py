import base64
import logging
import os
import secrets
from fastapi import FastAPI
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from app.database import Base, engine, SessionLocal
from app.routers import calculator, pig, batch, settings, ingredients

# ── ロギング設定 ─────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cost_simulator")


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    POST/PUT/DELETE リクエストに対して Referer/Origin チェックを行う簡易 CSRF 対策。
    Basic 認証が有効な場合はブラウザが自動送信するため、
    クロスオリジンフォームからの攻撃を Referer チェックで防ぐ。
    APP_PASS が設定されていない場合（ローカル開発）はスキップ。
    """
    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

    async def dispatch(self, request: Request, call_next):
        if request.method in self.SAFE_METHODS:
            return await call_next(request)
        # Referer または Origin が自サーバーと一致するか確認
        host = request.headers.get("host", "")
        referer = request.headers.get("referer", "")
        origin = request.headers.get("origin", "")
        check_val = referer or origin
        if check_val and host and host not in check_val:
            logger.warning("CSRF check failed: host=%s referer=%s origin=%s", host, referer, origin)
            return Response("不正なリクエストです", status_code=403)
        return await call_next(request)


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """
    APP_PASS 環境変数が設定されている場合のみ Basic 認証を有効化。
    ローカル開発時は APP_PASS を未設定にしておけばスキップされる。
    Railway 本番: Variables に APP_USER / APP_PASS を設定する。
    """
    def __init__(self, app, username: str, password: str):
        super().__init__(app)
        self._user = username
        self._pass = password

    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8")
                u, _, p = decoded.partition(":")
                ok = (
                    secrets.compare_digest(u, self._user)
                    and secrets.compare_digest(p, self._pass)
                )
                if ok:
                    return await call_next(request)
            except Exception:
                pass
        return Response(
            "認証が必要です",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Cost Simulator"'},
        )

Base.metadata.create_all(bind=engine)

_migrations = [
    "ALTER TABLE batch_ingredients ADD COLUMN price_per FLOAT DEFAULT 1",
    "ALTER TABLE ingredient_masters ADD COLUMN deleted_at TIMESTAMP",
    "ALTER TABLE batches ADD COLUMN portion_weight FLOAT",
    "ALTER TABLE batches ADD COLUMN portion_unit VARCHAR DEFAULT 'g'",
    "ALTER TABLE batch_ingredients ADD COLUMN price_unit VARCHAR DEFAULT 'kg'",
    "ALTER TABLE batches ADD COLUMN custom_rate FLOAT",
    "ALTER TABLE cuts ADD COLUMN gross_margin FLOAT",
    "ALTER TABLE cuts ADD COLUMN custom_gross_margin FLOAT",
    "ALTER TABLE recipe_templates ADD COLUMN default_customer_tier VARCHAR DEFAULT 'standard'",
    "ALTER TABLE recipe_templates ADD COLUMN default_gross_margin FLOAT",
    "ALTER TABLE batches ADD COLUMN waste_weight FLOAT",
    "ALTER TABLE batches ADD COLUMN raw_weight FLOAT",
]
with engine.connect() as conn:
    for sql in _migrations:
        try:
            conn.execute(text(sql))
            conn.commit()
        except Exception:
            pass

from app.seed_recipes import seed
_db = SessionLocal()
try:
    seed(_db)
finally:
    _db.close()

app = FastAPI(title="Cost Simulator")

# Basic 認証（APP_PASS が設定されている場合のみ有効）
_app_pass = os.getenv("APP_PASS", "")
if _app_pass:
    _app_user = os.getenv("APP_USER", "admin")
    app.add_middleware(BasicAuthMiddleware, username=_app_user, password=_app_pass)
    # CSRF チェック（Basic 認証が有効な場合のみ意味がある）
    app.add_middleware(CSRFMiddleware)

logger.info("アプリ起動完了 | DB=%s | BasicAuth=%s",
            os.getenv("DATABASE_URL", "sqlite")[:30], bool(_app_pass))

app.include_router(calculator.router)
app.include_router(pig.router)
app.include_router(batch.router)
app.include_router(settings.router)
app.include_router(ingredients.router)
