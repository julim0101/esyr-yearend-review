"""ESYR — 초기 데이터 생성

관리자 1명, 담당자 2명, 가상 직원 5명.

  python seed.py           # 계정·직원만 생성
  python seed.py --demo    # 시연 시나리오까지 자동 등록
"""
import os
import sys

from esyr import create_app
from esyr.models import DocType, Employee, User, db

ACCOUNTS = [
    ("admin", "관리자", "admin"),
    ("manager1", "임종욱", "manager"),
    ("manager2", "박서연", "manager"),
]
PASSWORD = "esyr1234"

EMPLOYEES = [
    ("H2046", "김하늘", "경영지원팀", "manager1"),
    ("H2078", "이서진", "영업1팀", "manager1"),
    ("H2103", "박도윤", "물류팀", "manager1"),
    ("H2125", "최유나", "연구소", "manager2"),
    ("H2127", "정민재", "IT팀", "manager2"),
]


def seed_basic():
    users = {}
    for username, name, role in ACCOUNTS:
        u = User.query.filter_by(username=username).first()
        if not u:
            u = User(username=username, display_name=name, role=role)
            u.set_password(PASSWORD)
            db.session.add(u)
            db.session.flush()
        users[username] = u

    for emp_no, name, dept, mgr in EMPLOYEES:
        if not Employee.query.filter_by(emp_no=emp_no).first():
            db.session.add(Employee(
                emp_no=emp_no, name=name, dept=dept, manager_id=users[mgr].id
            ))
    db.session.commit()
    return users


def seed_demo(app, users):
    """시연 시나리오를 실제 업로드 경로로 등록한다."""
    import hashlib
    from esyr import storage
    from esyr.compare import compare_versions
    from esyr.extract import run_extraction
    from esyr.models import DocumentGroup, DocumentVersion, Review, SubmitKind

    samples = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
    if not os.path.isdir(samples):
        print("samples 폴더가 없습니다. 먼저 python make_samples.py 를 실행하세요.")
        return

    emp = Employee.query.filter_by(emp_no="H2046").first()
    mgr = users["manager1"]
    year = 2025

    def add_version(group, filename, seq):
        src = os.path.join(samples, filename)
        if not os.path.exists(src):
            print("   (없음)", filename)
            return None
        import secrets
        with open(src, "rb") as f:
            raw = f.read()
        stored = f"{secrets.token_hex(16)}.pdf"
        storage.save_bytes(stored, raw)          # 로컬 또는 Supabase Storage
        ver = DocumentVersion(
            group_id=group.id, prev_version_id=group.current_version_id, seq=seq,
            stored_name=stored, orig_filename=filename,
            sha256=hashlib.sha256(raw).hexdigest(), byte_size=len(raw),
            submit_kind=SubmitKind.REVISION if seq > 1 else SubmitKind.NEW,
            uploaded_by_id=mgr.id,
        )
        db.session.add(ver)
        db.session.flush()
        group.current_version_id = ver.id
        path, tmp = storage.local_path(stored)
        run_extraction(ver, path)
        if tmp and path:
            os.remove(path)
        if seq > 1:
            compare_versions(group, ver)
        db.session.flush()
        return ver

    def make_group(doc_type, name):
        g = DocumentGroup(employee_id=emp.id, tax_year=year,
                          doc_type=doc_type, display_name=name)
        db.session.add(g)
        db.session.flush()
        return g

    def mark_done(ver, note=None, reason=None):
        db.session.add(Review(
            version_id=ver.id, run_id=ver.latest_run.id if ver.latest_run else None,
            reviewer_id=mgr.id, kind="complete", note=note, manual_reason=reason,
        ))
        ver.group.last_reviewed_version_id = ver.id
        db.session.flush()

    print("시연 시나리오 등록 중...")

    # ① 간소화자료 최초 → 검토 완료 → 의료비 수정본 제출
    g1 = make_group(DocType.SIMPLIFIED, "2025년 간소화자료 [의료비]")
    v1 = add_version(g1, "07_간소화자료_의료비_최초.pdf", 1)
    if v1:
        mark_done(v1, note="최초 제출분 확인")
        add_version(g1, "08_간소화자료_의료비_수정.pdf", 2)

    # ② 행복나눔재단 영수증 최초 → 완료 → 금액 수정본 (100,000 → 150,000)
    g2 = make_group(DocType.DONATION, "행복나눔재단 기부금영수증")
    v1 = add_version(g2, "01_기부금영수증_행복나눔_최초.pdf", 1)
    if v1:
        mark_done(v1, note="원본 확인 완료")
        add_version(g2, "02_기부금영수증_행복나눔_수정_금액변경.pdf", 2)

    # ③ 합계는 같은데 내역이 바뀐 사례
    g3 = make_group(DocType.DONATION, "연화사 기부금영수증(종교단체)")
    v1 = add_version(g3, "05_기부금영수증_연화사_최초.pdf", 1)
    if v1:
        mark_done(v1)
        add_version(g3, "06_기부금영수증_연화사_합계같고_내역변경.pdf", 2)

    # ④ 신규 기관 추가 — 기존 완료분을 건드리지 않는다
    g4 = make_group(DocType.DONATION, "푸른숲복지회 기부금영수증")
    add_version(g4, "04_기부금영수증_푸른숲_신규추가.pdf", 1)

    # ⑤ 미지원 서식 — 원본 조회 + 수동 검토 경로
    g5 = make_group(DocType.OTHER, "사찰등록증 (첨부서류)")
    add_version(g5, "09_사찰등록증_첨부서류.pdf", 1)

    # ⑥ 읽기 실패 사례 — 추출 확인 필요로 남는다
    g6 = make_group(DocType.DONATION, "판독 불가 스캔 영수증")
    add_version(g6, "10_읽기실패_빈페이지포함_스캔.pdf", 1)

    db.session.commit()
    print("완료.")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        db.create_all()
        users = seed_basic()
        print(f"계정 {len(ACCOUNTS)}개 · 직원 {len(EMPLOYEES)}명 준비 (비밀번호: {PASSWORD})")
        if "--demo" in sys.argv:
            seed_demo(app, users)
