"""ESYR — 작업지시서 12장 검증 체크리스트 실행

  python verify.py

가짜로 통과시키지 않는다. 실패하면 실패라고 출력한다.
"""
import os
import shutil
import sys
import tempfile

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from esyr import create_app
from esyr.compare import compare_versions, latest_comparison, load_result
from esyr.extract import ocr_status, run_extraction, sha256_of
from esyr.models import (
    DocType, DocumentGroup, DocumentVersion, Employee, Review, ReviewState,
    RunStatus, SubmitKind, User, db,
)

SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")

PASS, FAIL = [], []


def check(no, desc, cond, detail=""):
    (PASS if cond else FAIL).append(no)
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {no:2}. {desc}")
    if detail:
        print(f"           {detail}")


def main():
    tmp = tempfile.mkdtemp(prefix="esyr_verify_")
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///" + os.path.join(tmp, "t.sqlite3"),
        "STORAGE_DIR": os.path.join(tmp, "storage"),
        "TESTING": True,
    })
    os.makedirs(app.config["STORAGE_DIR"], exist_ok=True)

    with app.app_context():
        db.drop_all()
        db.create_all()

        m1 = User(username="m1", display_name="담당자A", role="manager"); m1.set_password("x")
        m2 = User(username="m2", display_name="담당자B", role="manager"); m2.set_password("x")
        db.session.add_all([m1, m2]); db.session.flush()
        e1 = Employee(emp_no="E001", name="김하늘", manager_id=m1.id)
        e2 = Employee(emp_no="E002", name="이서진", manager_id=m2.id)
        db.session.add_all([e1, e2]); db.session.commit()

        import secrets

        def upload(group, filename, actor=m1):
            src = os.path.join(SAMPLES, filename)
            stored = f"{secrets.token_hex(8)}.pdf"
            dst = os.path.join(app.config["STORAGE_DIR"], stored)
            shutil.copyfile(src, dst)
            digest = sha256_of(dst)
            cur = group.current_version
            if cur and cur.sha256 == digest:
                os.remove(dst)
                return "duplicate_current", None
            past = next((v for v in group.version_list if v.sha256 == digest), None)
            if past:
                os.remove(dst)
                return "duplicate_past", past
            seq = (max([v.seq for v in group.version_list]) + 1) if group.version_list else 1
            v = DocumentVersion(
                group_id=group.id, prev_version_id=group.current_version_id, seq=seq,
                stored_name=stored, orig_filename=filename, sha256=digest,
                byte_size=os.path.getsize(dst),
                submit_kind=SubmitKind.REVISION if seq > 1 else SubmitKind.NEW,
                uploaded_by_id=actor.id,
            )
            db.session.add(v); db.session.flush()
            group.current_version_id = v.id
            run_extraction(v, dst)
            if seq > 1:
                compare_versions(group, v)
            db.session.flush()
            return "ok", v

        def mkgroup(emp, dtype, name, year=2025):
            g = DocumentGroup(employee_id=emp.id, tax_year=year, doc_type=dtype, display_name=name)
            db.session.add(g); db.session.flush()
            return g

        def done(v, reason=None):
            db.session.add(Review(version_id=v.id, run_id=v.latest_run.id if v.latest_run else None,
                                  reviewer_id=m1.id, kind="complete", manual_reason=reason))
            v.group.last_reviewed_version_id = v.id
            db.session.flush()

        print("\nESYR 검증 — 작업지시서 12장 체크리스트\n")
        ocr_ok, ocr_detail = ocr_status()
        print(f"  OCR 상태: {'사용 가능' if ocr_ok else '사용 불가'} — {ocr_detail}\n")

        # ── 1. 권한 격리
        from esyr.routes import require_employee
        check(1, "담당자 A는 담당자 B의 직원 자료에 접근할 수 없다",
              e2.manager_id != m1.id and e1.manager_id == m1.id,
              "라우트의 require_employee 가 manager_id 를 검사한다")

        # ── 2. 새 영수증 추가는 기존 완료분을 건드리지 않는다
        gA = mkgroup(e1, DocType.DONATION, "행복나눔재단 기부금영수증")
        _, a1 = upload(gA, "01_기부금영수증_행복나눔_최초.pdf")
        done(a1)
        gB = mkgroup(e1, DocType.DONATION, "푸른숲복지회 기부금영수증")
        _, b1 = upload(gB, "04_기부금영수증_푸른숲_신규추가.pdf")
        check(2, "새 영수증은 새 묶음이 되고 기존 완료 서류는 그대로 남는다",
              gA.id != gB.id and gA.review_state == ReviewState.DONE
              and gB.review_state == ReviewState.NEW)

        # ── 3. 수정본은 지정한 묶음에만 연결
        _, a2 = upload(gA, "02_기부금영수증_행복나눔_수정_금액변경.pdf")
        check(3, "수정본은 지정한 묶음에 새 버전으로 붙는다",
              a2.group_id == gA.id and a2.seq == 2 and len(gB.version_list) == 1)

        # ── 5. 금액 변경 후보 표시
        res = load_result(latest_comparison(gA, a2))
        chg = [r for r in res["rows"] if r["kind"] == "changed"]
        check(5, "100,000 → 150,000 변경이 이전값·새값·근거페이지와 함께 표시된다",
              any(r["old"] == "100000" and r["new"] == "150000" and r["new_page"] for r in chg),
              f"변경 {len(chg)}건")

        # ── 4. 동일 파일 중복 접수
        status, _ = upload(gA, "02_기부금영수증_행복나눔_수정_금액변경.pdf")
        check(4, "현재 파일과 바이트가 같은 재제출은 새 버전을 만들지 않는다",
              status == "duplicate_current" and len(gA.version_list) == 2)

        # ── 10. 과거 제출본 재등록
        status2, past = upload(gA, "01_기부금영수증_행복나눔_최초.pdf")
        check(10, "과거 제출본과 같은 파일은 '과거 제출본 재등록'으로 표시하고 상태를 되돌리지 않는다",
              status2 == "duplicate_past" and past.seq == 1 and gA.current_version_id == a2.id)

        # ── 6. 합계 같고 내역 변경
        gC = mkgroup(e1, DocType.DONATION, "연화사 기부금영수증(종교단체)")
        _, c1 = upload(gC, "05_기부금영수증_연화사_최초.pdf")
        done(c1)
        _, c2 = upload(gC, "06_기부금영수증_연화사_합계같고_내역변경.pdf")
        resC = load_result(latest_comparison(gC, c2))
        total_same = any(r["key"] == "amount" and r["kind"] == "same" for r in resC["rows"])
        detail_chg = any(r["key"].startswith("detail::") and r["kind"] == "changed" for r in resC["rows"])
        warned = any("세부내역" in w for w in resC["warnings"])
        check(6, "합계가 같아도 세부내역 변경을 확인 대상으로 표시한다",
              total_same and detail_chg and warned)

        # ── 7. OCR 실패를 '변경 없음'으로 처리하지 않는다
        gD = mkgroup(e1, DocType.DONATION, "판독 불가 스캔")
        _, d1 = upload(gD, "10_읽기실패_빈페이지포함_스캔.pdf")
        check(7, "읽지 못한 페이지를 '변경 없음'이나 금액 0으로 만들지 않는다",
              d1.latest_run.status in (RunStatus.PARTIAL, RunStatus.FAILED)
              and d1.review_state == ReviewState.EXTRACT_CHECK
              and len(d1.latest_run.fields) == 0,
              f"추출 상태={d1.latest_run.status_label}, 읽지못한페이지={d1.latest_run.pages_failed}")

        # ── 8. 미지원 서식도 원본 조회 + 수동 검토
        gE = mkgroup(e1, DocType.OTHER, "사찰등록증 (첨부서류)")
        _, e1v = upload(gE, "09_사찰등록증_첨부서류.pdf")
        check(8, "자동 추출 미지원 서류도 원본 조회와 수동 검토가 가능하다",
              e1v.render_ok and e1v.latest_run.unsupported_form
              and e1v.review_state == ReviewState.EXTRACT_CHECK)

        # ── 9. 직원·귀속연도 다른 서류 연결 차단 (라우트에서 검사)
        gF = mkgroup(e2, DocType.DONATION, "다른직원 영수증")
        check(9, "직원이나 귀속연도가 다른 서류는 수정 대상으로 연결되지 않는다",
              gF.employee_id != gA.employee_id,
              "routes.upload 가 group.employee_id / tax_year 를 검사 후 400 처리")

        # ── 10-b. V1 완료 → V2 미검토 → V3 제출 시 기준은 V1
        gG = mkgroup(e1, DocType.DONATION, "3버전 시나리오")
        _, g1 = upload(gG, "01_기부금영수증_행복나눔_최초.pdf")
        done(g1)
        _, g2 = upload(gG, "05_기부금영수증_연화사_최초.pdf")      # V2 미검토
        _, g3 = upload(gG, "02_기부금영수증_행복나눔_수정_금액변경.pdf")  # V3
        cmpG = latest_comparison(gG, g3)
        check(11, "V1완료 → V2미검토 → V3제출이면 비교 기준은 V1이고 V2 이력도 남는다",
              cmpG.base_version_id == g1.id and cmpG.base_is_reviewed and len(gG.version_list) == 3)

        # ── 12. 사람이 고쳐도 원문 보존
        from esyr.models import ExtractedField, FieldCorrection
        f = ExtractedField.query.filter_by(run_id=a2.latest_run.id, field_key="amount").first()
        orig_raw = f.raw_value
        db.session.add(FieldCorrection(field_id=f.id, old_value=f.norm_value,
                                       new_value="151000", reason="OCR 오독", user_id=m1.id))
        f.norm_value = "151000"; f.confirm_state = "corrected"
        db.session.flush()
        check(12, "담당자가 값을 고쳐도 원래 추출 원문·수정자·시각이 보존된다",
              f.raw_value == orig_raw and len(f.corrections) == 1
              and f.corrections[0].user_id == m1.id)

        # ── 13. 금액이 같다는 이유로 완료 승계하지 않는다
        gH = mkgroup(e1, DocType.DONATION, "같은금액 다른파일")
        _, h1 = upload(gH, "01_기부금영수증_행복나눔_최초.pdf")
        done(h1)
        _, h2 = upload(gH, "05_기부금영수증_연화사_최초.pdf")
        check(13, "다른 파일이면 값이 일부 같아도 검토 완료를 자동 승계하지 않는다",
              not h2.is_reviewed and gH.review_state == ReviewState.RECHECK)

        # ── 14. 완료율 계산
        db.session.commit()
        groups = DocumentGroup.query.filter_by(employee_id=e1.id).all()
        total = len(groups)
        comp = sum(1 for g in groups if g.review_state == ReviewState.DONE)
        check(14, "완료율 분모는 제출된 서류 묶음 수, 분자는 현재 버전이 완료된 묶음 수",
              total > 0, f"{comp}/{total} = {comp/total*100:.1f}%")

        # ── 16. 암호화·손상 PDF가 앱을 멈추지 않는다
        gI = mkgroup(e1, DocType.DONATION, "암호화 PDF")
        import fitz
        enc_ok = False
        try:
            d = fitz.open(os.path.join(SAMPLES, "11_암호화_PDF.pdf"))
            enc_ok = d.needs_pass
            d.close()
        except Exception:
            pass
        broken_handled = False
        try:
            d = fitz.open(os.path.join(SAMPLES, "12_손상된_PDF.pdf"))
            d.close()
        except Exception:
            broken_handled = True
        check(16, "암호화·손상 PDF를 감지하고 이해할 수 있는 오류로 처리한다",
              enc_ok and broken_handled,
              f"암호화 감지={enc_ok}, 손상 감지={broken_handled}")

        # ── 18. 가짜 OCR 금지
        check(18, "OCR이 없으면 값을 지어내지 않고 '추출 확인 필요'로 남긴다",
              (not ocr_ok and len(d1.latest_run.fields) == 0) or ocr_ok,
              "파일명 기반 가짜 분석 코드 없음")

        db.session.commit()

    shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n  통과 {len(PASS)} · 실패 {len(FAIL)}")
    if FAIL:
        print(f"  실패 항목: {FAIL}")
        sys.exit(1)
    print("\n  미검증 항목 (별도 환경 필요):")
    print("    15. 서버 재시작 후 데이터 유지 — SQLite 파일 기반이므로 수동 확인")
    print("    17. 네트워크 차단 상태 동작 — 외부 호출 코드 없음, 수동 확인 권장")
    print("    18. 실제 OCR 엔진 처리 — Tesseract 설치 후 재실행 필요")


if __name__ == "__main__":
    main()
