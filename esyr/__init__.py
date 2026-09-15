"""ESYR · Etners Smart Year-end Review
연말정산 증빙 PDF 추가·수정 제출자료 검토 관리

앱 팩토리.

환경변수로 로컬 실행과 서버리스 배포를 같은 코드로 쓴다.
  DATABASE_URL          비우면 SQLite(로컬). Supabase Postgres 주소를 넣으면 그쪽을 쓴다.
  SUPABASE_URL / SUPABASE_SERVICE_KEY / SUPABASE_BUCKET
                        셋 다 있으면 원본 PDF를 Supabase Storage 에 보관한다.
  ESYR_SECRET_KEY       세션 서명 키. 배포 시 반드시 지정한다.
"""
import os
import secrets

from flask import Flask

from . import storage
from .models import db

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
STORAGE_DIR = os.path.join(INSTANCE_DIR, "storage")


def _database_uri():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return "sqlite:///" + os.path.join(INSTANCE_DIR, "esyr.sqlite3")
    # Supabase / Heroku 계열이 주는 postgres:// 를 SQLAlchemy 드라이버 형식으로 맞춘다
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def create_app(config=None):
    app = Flask(__name__, instance_path=INSTANCE_DIR)

    serverless = bool(os.environ.get("VERCEL"))
    if not serverless:
        os.makedirs(INSTANCE_DIR, exist_ok=True)
        os.makedirs(STORAGE_DIR, exist_ok=True)

    app.config.update(
        SECRET_KEY=os.environ.get("ESYR_SECRET_KEY") or secrets.token_hex(32),
        SQLALCHEMY_DATABASE_URI=_database_uri(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        STORAGE_DIR=STORAGE_DIR,
        SUPABASE_URL=os.environ.get("SUPABASE_URL"),
        SUPABASE_SERVICE_KEY=os.environ.get("SUPABASE_SERVICE_KEY"),
        SUPABASE_BUCKET=os.environ.get("SUPABASE_BUCKET"),
        MAX_CONTENT_LENGTH=20 * 1024 * 1024,   # 파일당 20MB
        MAX_PDF_PAGES=50,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=serverless,
        IS_SERVERLESS=serverless,
    )
    if config:
        app.config.update(config)

    db.init_app(app)
    storage.init_app(app)

    from .routes import bp
    app.register_blueprint(bp)

    # 서버리스에서는 매 요청마다 create_all 을 돌리지 않는다 (init_db.py 로 1회 생성)
    if not serverless:
        with app.app_context():
            db.create_all()

    return app
