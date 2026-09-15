"""ESYR · Etners Smart Year-end Review
연말정산 증빙 PDF 추가·수정 제출자료 검토 관리

앱 팩토리.
"""
import os
import secrets

from flask import Flask

from .models import db

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
STORAGE_DIR = os.path.join(INSTANCE_DIR, "storage")  # 원본 PDF 비공개 보관


def create_app(config=None):
    app = Flask(__name__, instance_path=INSTANCE_DIR)

    os.makedirs(INSTANCE_DIR, exist_ok=True)
    os.makedirs(STORAGE_DIR, exist_ok=True)

    app.config.update(
        SECRET_KEY=os.environ.get("ESYR_SECRET_KEY") or secrets.token_hex(32),
        SQLALCHEMY_DATABASE_URI="sqlite:///" + os.path.join(INSTANCE_DIR, "esyr.sqlite3"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        STORAGE_DIR=STORAGE_DIR,
        MAX_CONTENT_LENGTH=20 * 1024 * 1024,   # 파일당 20MB (설정에서 변경 가능)
        MAX_PDF_PAGES=50,                       # 파일당 50페이지
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if config:
        app.config.update(config)

    db.init_app(app)

    from .routes import bp
    app.register_blueprint(bp)

    with app.app_context():
        db.create_all()

    return app
