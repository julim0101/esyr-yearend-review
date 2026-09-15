"""배포 환경(Supabase Postgres)에 테이블과 초기 계정을 1회 생성한다.

  DATABASE_URL=... python init_db.py
  DATABASE_URL=... python init_db.py --demo
"""
import sys

from esyr import create_app
from esyr.models import db
from seed import seed_basic, seed_demo

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        db.create_all()
        users = seed_basic()
        print("테이블·계정 준비 완료 (비밀번호: esyr1234)")
        print("DB :", app.config["SQLALCHEMY_DATABASE_URI"].split("@")[-1])
        from esyr import storage
        print("저장소:", storage.describe())
        if "--demo" in sys.argv:
            seed_demo(app, users)
