"""ESYR — 화면과 처리

권한 규칙 (작업지시서 2장·10장):
  · 담당자는 자기에게 배정된 직원 자료만 열람·등록·검토한다.
  · 관리자는 전체를 본다.
  · 원본 PDF·페이지 이미지·CSV 모두 서버에서 권한을 확인한다.
  · 원본은 static 이 아니라 인증된 경로로만 내보낸다.
"""
import csv
import hashlib
import io
import os
import secrets
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint, Response, abort, current_app, flash, g, redirect,
    render_template, request, session, url_for,
)

from .compare import (
    change_summary_text, compare_versions, latest_comparison, load_result,
)
from . import storage
from .extract import ocr_status, render_page_png, run_extraction, sha256_of
from .models import (
    ChangeKind, DocType, DocumentGroup, DocumentVersion, Employee,
    ExtractedField, ExtractionRun, FieldCorrection, Review, ReviewState,
    RunStatus, SubmitKind, User, db, log,
)

bp = Blueprint("main", __name__)


# ─────────────────────────────────────────────────────────────
# 인증 / 권한
# ─────────────────────────────────────────────────────────────

@bp.before_app_request
def load_user():
    g.user = None
    uid = session.get("uid")
    if uid:
        g.user = db.session.get(User, uid)
    # CSRF 토큰
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not g.user:
            return redirect(url_for("main.login", next=request.path))
        return f(*a, **kw)
    return wrapper


def check_csrf():
    if request.method == "POST":
        if request.form.get("csrf") != session.get("csrf"):
            abort(400, "CSRF 토큰이 올바르지 않습니다.")


def visible_employees():
    q = Employee.query
    if not g.user.is_admin:
        q = q.filter_by(manager_id=g.user.id)
    return q.order_by(Employee.emp_no).all()


def require_employee(emp_id):
    emp = db.session.get(Employee, emp_id)
    if not emp:
        abort(404)
    if not g.user.is_admin and emp.manager_id != g.user.id:
        abort(403, "배정되지 않은 직원의 자료입니다.")
    return emp


def require_group(gid):
    grp = db.session.get(DocumentGroup, gid)
    if not grp:
        abort(404)
    require_employee(grp.employee_id)
    return grp


def require_version(vid):
    ver = db.session.get(DocumentVersion, vid)
    if not ver:
        abort(404)
    require_employee(ver.group.employee_id)
    return ver


@bp.app_context_processor
def inject():
    return dict(
        ReviewState=ReviewState, RunStatus=RunStatus, DocType=DocType,
        SubmitKind=SubmitKind, ChangeKind=ChangeKind,
        csrf_token=session.get("csrf", ""),
        app_name="ESYR", app_full="Etners Smart Year-end Review",
    )


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = User.query.filter_by(username=request.form.get("username", "").strip()).first()
        if u and u.active and u.check_password(request.form.get("password", "")):
            session.clear()
            session["uid"] = u.id
            session["csrf"] = secrets.token_hex(16)
            log("login", "user", u.id, actor=u)
            db.session.commit()
            return redirect(request.args.get("next") or url_for("main.dashboard"))
        flash("아이디 또는 비밀번호가 올바르지 않습니다.", "error")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login"))


# ─────────────────────────────────────────────────────────────
# 대시보드
# ─────────────────────────────────────────────────────────────

def _groups_query(tax_year=None):
    emp_ids = [e.id for e in visible_employees()]
    q = DocumentGroup.query.filter(DocumentGroup.employee_id.in_(emp_ids or [-1]))
    if tax_year:
        q = q.filter_by(tax_year=tax_year)
    return q


@bp.route("/")
@login_required
def dashboard():
    years = sorted({g_.tax_year for g_ in _groups_query().all()}, reverse=True)
    tax_year = request.args.get("year", type=int) or (years[0] if years else datetime.now().year - 1)
    kw = (request.args.get("q") or "").strip()
    state_filter = request.args.get("state") or ""
    type_filter = request.args.get("type") or ""

    groups = _groups_query(tax_year).all()

    rows = []
    for grp in groups:
        cur = grp.current_version
        state = grp.review_state
        if state_filter and state != state_filter:
            continue
        if type_filter and grp.doc_type != type_filter:
            continue
        if kw:
            hay = f"{grp.employee.emp_no} {grp.employee.name} {grp.display_name}"
            if kw.lower() not in hay.lower():
                continue
        cmp_ = latest_comparison(grp, cur) if cur else None
        rows.append(dict(
            group=grp, version=cur, state=state,
            summary=change_summary_text(load_result(cmp_)) if cmp_ else "",
        ))

    counts = {k: 0 for k in ReviewState.LABELS}
    for grp in groups:
        counts[grp.review_state] += 1
    run_counts = {k: 0 for k in RunStatus.LABELS}
    for grp in groups:
        cur = grp.current_version
        run = cur.latest_run if cur else None
        if run:
            run_counts[run.status] += 1

    total = len(groups)
    done = counts[ReviewState.DONE]
    rate = (done / total * 100) if total else None

    ocr_ok, ocr_detail = ocr_status()

    return render_template(
        "dashboard.html", rows=rows, years=years, tax_year=tax_year,
        counts=counts, run_counts=run_counts, total=total, done=done, rate=rate,
        kw=kw, state_filter=state_filter, type_filter=type_filter,
        employees=visible_employees(), ocr_ok=ocr_ok, ocr_detail=ocr_detail,
    )


@bp.route("/employee/<int:emp_id>")
@login_required
def employee(emp_id):
    emp = require_employee(emp_id)
    years = sorted({g_.tax_year for g_ in emp.doc_groups}, reverse=True)
    tax_year = request.args.get("year", type=int) or (years[0] if years else datetime.now().year - 1)
    groups = [g_ for g_ in emp.doc_groups if g_.tax_year == tax_year]
    return render_template(
        "employee.html", emp=emp, groups=groups, years=years, tax_year=tax_year
    )


# ─────────────────────────────────────────────────────────────
# 업로드
# ─────────────────────────────────────────────────────────────

@bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    check_csrf()
    employees = visible_employees()

    if request.method == "POST":
        emp = require_employee(request.form.get("employee_id", type=int))
        tax_year = request.form.get("tax_year", type=int)
        submit_kind = request.form.get("submit_kind")
        file = request.files.get("pdf")

        if not file or not file.filename:
            flash("PDF 파일을 선택해 주세요.", "error")
            return redirect(url_for("main.upload"))
        if not tax_year:
            flash("귀속연도를 입력해 주세요.", "error")
            return redirect(url_for("main.upload"))

        # 저장 이름은 서버가 만든다. 업로드 파일명을 경로로 쓰지 않는다.
        stored = f"{secrets.token_hex(16)}.pdf"
        raw = file.read()
        size = len(raw)
        digest = hashlib.sha256(raw).hexdigest()

        # 실제로 PDF로 열리는지 확인 (확장자만 믿지 않는다)
        import fitz
        try:
            d = fitz.open(stream=raw, filetype="pdf")
            needs_pass = d.needs_pass
            d.close()
        except Exception as e:  # noqa: BLE001
            flash(f"PDF로 열 수 없는 파일입니다: {e}", "error")
            return redirect(url_for("main.upload"))
        if needs_pass:
            flash("암호가 설정된 PDF입니다. 암호 해제 후 다시 제출해 주세요.", "error")
            return redirect(url_for("main.upload"))

        if submit_kind == SubmitKind.REVISION:
            grp = require_group(request.form.get("group_id", type=int))
            # 직원·귀속연도가 다른 서류로는 연결할 수 없다
            if grp.employee_id != emp.id or grp.tax_year != tax_year:
                abort(400, "직원 또는 귀속연도가 다른 서류를 수정 대상으로 지정할 수 없습니다.")
        else:
            doc_type = request.form.get("doc_type") or DocType.OTHER
            name = (request.form.get("display_name") or "").strip()
            if not name:
                flash("서류 표시명을 입력해 주세요. 예: A기관 기부금영수증", "error")
                return redirect(url_for("main.upload"))
            grp = DocumentGroup(
                employee_id=emp.id, tax_year=tax_year,
                doc_type=doc_type, display_name=name,
            )
            db.session.add(grp)
            db.session.flush()

        # ── 중복 판정 (권한 범위 = 이 묶음 안에서만) ─────────────
        same_current = (
            grp.current_version is not None and grp.current_version.sha256 == digest
        )
        same_past = next(
            (v for v in grp.version_list if v.sha256 == digest and not same_current), None
        )

        if same_current:
            log("duplicate_intake", "group", grp.id,
                f"현재 파일과 동일한 재업로드 (sha {digest[:12]})", actor=g.user)
            db.session.commit()
            flash("현재 파일과 내용이 완전히 같습니다. 중복 접수로 처리했고 검토 상태는 그대로 둡니다.", "warn")
            return redirect(url_for("main.group_detail", gid=grp.id))

        if same_past:
            log("past_version_reupload", "group", grp.id,
                f"과거 제출본({same_past.label})과 동일", actor=g.user)
            db.session.commit()
            flash(
                f"과거 제출본({same_past.label})과 내용이 같은 파일입니다. "
                "현재 상태를 되돌리지 않았습니다. 수정본이 맞는지 확인해 주세요.", "warn",
            )
            return redirect(url_for("main.group_detail", gid=grp.id))

        vlist = grp.version_list
        seq = (max([v.seq for v in vlist]) + 1) if vlist else 1
        ver = DocumentVersion(
            group_id=grp.id,
            prev_version_id=grp.current_version_id,
            seq=seq,
            stored_name=stored,
            orig_filename=file.filename,
            sha256=digest,
            byte_size=size,
            submit_kind=SubmitKind.REVISION if seq > 1 else SubmitKind.NEW,
            uploaded_by_id=g.user.id,
        )
        db.session.add(ver)
        db.session.flush()
        grp.current_version_id = ver.id

        storage.save_bytes(stored, raw)
        path, tmp = storage.local_path(stored)
        run_extraction(ver, path)
        if tmp and path:
            os.remove(path)
        if seq > 1:
            compare_versions(grp, ver)

        log("upload", "version", ver.id,
            f"{grp.display_name} {ver.label}", actor=g.user)
        db.session.commit()
        flash(f"{grp.display_name} · {ver.label} 등록했습니다.", "ok")
        return redirect(url_for("main.version_detail", vid=ver.id))

    # GET
    emp_id = request.args.get("employee_id", type=int)
    groups = []
    if emp_id:
        emp = require_employee(emp_id)
        groups = emp.doc_groups
    return render_template(
        "upload.html", employees=employees, groups=groups,
        sel_emp=emp_id, default_year=datetime.now().year - 1,
    )


# ─────────────────────────────────────────────────────────────
# 서류 / 버전 상세
# ─────────────────────────────────────────────────────────────

@bp.route("/group/<int:gid>")
@login_required
def group_detail(gid):
    grp = require_group(gid)
    return redirect(url_for("main.version_detail", vid=grp.current_version_id)) \
        if grp.current_version_id else redirect(url_for("main.employee", emp_id=grp.employee_id))


@bp.route("/version/<int:vid>")
@login_required
def version_detail(vid):
    ver = require_version(vid)
    grp = ver.group
    run = ver.latest_run
    cmp_ = latest_comparison(grp, ver)
    result = load_result(cmp_)
    base_ver = db.session.get(DocumentVersion, cmp_.base_version_id) if cmp_ and cmp_.base_version_id else None
    page = request.args.get("page", type=int) or 1
    return render_template(
        "version.html", ver=ver, grp=grp, run=run, cmp_=cmp_, result=result,
        base_ver=base_ver, page=page,
        is_current=(grp.current_version_id == ver.id),
    )


@bp.route("/version/<int:vid>/page/<int:no>.png")
@login_required
def page_png(vid, no):
    ver = require_version(vid)
    path, tmp = storage.local_path(ver.stored_name)
    data = render_page_png(path, no) if path else None
    if tmp and path:
        os.remove(path)
    if not data:
        abort(404)
    return Response(data, mimetype="image/png")


@bp.route("/version/<int:vid>/file")
@login_required
def version_file(vid):
    ver = require_version(vid)
    data = storage.read_bytes(ver.stored_name)
    if data is None:
        abort(404)
    return Response(
        data, mimetype="application/pdf",
        headers={"Content-Disposition": f'inline; filename="doc-{ver.id}.pdf"'},
    )


@bp.route("/field/<int:fid>/correct", methods=["POST"])
@login_required
def correct_field(fid):
    check_csrf()
    field = db.session.get(ExtractedField, fid)
    if not field:
        abort(404)
    ver = db.session.get(DocumentVersion, field.run.version_id)
    require_version(ver.id)

    new_val = (request.form.get("value") or "").strip()
    reason = (request.form.get("reason") or "").strip()
    old_val = field.display_value

    if new_val != old_val:
        db.session.add(FieldCorrection(
            field_id=field.id, old_value=old_val, new_value=new_val,
            reason=reason or None, user_id=g.user.id,
        ))
        # 원문(raw_value)은 그대로 둔다. 사용값만 바꾼다.
        field.norm_value = new_val
        field.confirm_state = "corrected"
        log("field_correct", "field", field.id,
            f"{field.field_label}: {old_val} → {new_val}", actor=g.user)
    else:
        field.confirm_state = "confirmed"

    # 값이 바뀌었으면 비교를 다시 한다
    if ver.group.current_version_id == ver.id and ver.seq > 1:
        compare_versions(ver.group, ver)
    db.session.commit()
    flash("추출값을 저장했습니다.", "ok")
    return redirect(url_for("main.version_detail", vid=ver.id))


@bp.route("/version/<int:vid>/complete", methods=["POST"])
@login_required
def complete(vid):
    check_csrf()
    ver = require_version(vid)
    grp = ver.group

    # 새 버전이 들어온 뒤 옛 버전 화면에서 완료를 눌러도 현재 버전은 완료되지 않는다
    if grp.current_version_id != ver.id:
        flash("이 버전은 더 이상 현재 버전이 아닙니다. 최신 버전을 확인해 주세요.", "error")
        return redirect(url_for("main.version_detail", vid=grp.current_version_id))

    # 원본을 한 장도 못 본 파일은 앱에서 완료할 수 없다
    if not ver.render_ok:
        flash("원본 페이지를 표시할 수 없는 파일입니다. 앱에서 검토 완료할 수 없습니다.", "error")
        return redirect(url_for("main.version_detail", vid=ver.id))

    run = ver.latest_run
    manual_reason = (request.form.get("manual_reason") or "").strip()
    if run and (run.has_unread or run.status in (RunStatus.PARTIAL, RunStatus.FAILED)):
        if not manual_reason:
            flash(
                "읽지 못한 페이지나 미지원 서식이 있습니다. "
                "원본을 직접 확인한 내용을 사유로 남겨야 완료할 수 있습니다.", "error",
            )
            return redirect(url_for("main.version_detail", vid=ver.id))

    db.session.add(Review(
        version_id=ver.id, run_id=run.id if run else None,
        reviewer_id=g.user.id, kind="complete",
        note=(request.form.get("note") or "").strip() or None,
        manual_reason=manual_reason or None,
    ))
    grp.last_reviewed_version_id = ver.id
    log("review_complete", "version", ver.id, grp.display_name, actor=g.user)
    db.session.commit()
    flash(f"{grp.display_name} · {ver.label} 검토 완료로 기록했습니다.", "ok")
    return redirect(url_for("main.employee", emp_id=grp.employee_id, year=grp.tax_year))


# ─────────────────────────────────────────────────────────────
# 내보내기
# ─────────────────────────────────────────────────────────────

@bp.route("/export.csv")
@login_required
def export_csv():
    tax_year = request.args.get("year", type=int)
    groups = _groups_query(tax_year).all()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["사번", "성명", "귀속연도", "서류명", "서류종류",
                "현재버전", "검토상태", "변경요약", "검토자", "검토시각"])
    for grp in groups:
        cur = grp.current_version
        cmp_ = latest_comparison(grp, cur) if cur else None
        summary = change_summary_text(load_result(cmp_)) if cmp_ else ""
        rev = next((r for r in reversed(cur.reviews) if r.kind == "complete"), None) if cur else None
        w.writerow([
            _safe_csv(grp.employee.emp_no), _safe_csv(grp.employee.name), grp.tax_year,
            _safe_csv(grp.display_name), grp.doc_type_label,
            cur.label if cur else "", ReviewState.LABELS[grp.review_state],
            _safe_csv(summary),
            rev.reviewer.display_name if rev else "",
            rev.created_at.strftime("%Y-%m-%d %H:%M") if rev else "",
        ])

    data = "﻿" + buf.getvalue()  # UTF-8 BOM
    fname = f"ESYR_검토현황_{tax_year or 'all'}.csv"
    return Response(
        data.encode("utf-8"), mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _safe_csv(v):
    """엑셀 수식 실행 방지."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


@bp.route("/health")
def health():
    ok, detail = ocr_status()
    return dict(app="ESYR", ocr_available=ok, ocr_detail=detail,
                storage=storage.backend(), storage_detail=storage.describe(),
                db=("postgres" if "postgres" in current_app.config["SQLALCHEMY_DATABASE_URI"] else "sqlite"))
