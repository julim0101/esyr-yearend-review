"""ESYR · Etners Smart Year-end Review — 데이터 모델

작업지시서 9장(데이터 모델과 처리 일관성)을 그대로 따른다.

핵심 분리:
  DocumentGroup  : 하나의 논리적 서류 (예: 'A기관 기부금영수증')
  DocumentVersion: 그 서류의 제출본 (최초/수정1/수정2...)
  ExtractionRun  : 특정 버전을 읽은 결과 판본 (재추출하면 새 판본, 버전은 그대로)
  Review         : 특정 버전 + 특정 추출 판본에 대한 담당자 확인 기록

문서 버전과 추출 판본을 절대 혼동하지 않는다.
같은 원본을 다시 읽었다고 제출 버전이 늘어나지 않는다.
"""
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


# ─────────────────────────────────────────────────────────────
# 상태 상수 — 작업지시서 8장
# ─────────────────────────────────────────────────────────────

class RunStatus:
    """추출 작업 상태 (기계가 정하는 것)"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"

    LABELS = {
        PENDING: "대기",
        RUNNING: "처리 중",
        SUCCESS: "성공",
        PARTIAL: "부분 성공",
        FAILED: "실패",
    }


class ReviewState:
    """업무 검토 상태 (사람이 정하는 것)"""
    NEW = "new"                    # 신규 검토
    RECHECK = "recheck"            # 재확인 필요
    EXTRACT_CHECK = "extract_check"  # 추출 확인 필요
    DONE = "done"                  # 검토 완료

    LABELS = {
        NEW: "신규 검토",
        RECHECK: "재확인 필요",
        EXTRACT_CHECK: "추출 확인 필요",
        DONE: "검토 완료",
    }


class DocType:
    SIMPLIFIED = "simplified"   # 간소화자료
    DONATION = "donation"       # 기부금영수증
    OTHER = "other"             # 기타 (자동 추출 미지원)

    LABELS = {
        SIMPLIFIED: "간소화자료",
        DONATION: "기부금영수증",
        OTHER: "기타",
    }


class SubmitKind:
    NEW = "new"            # 새 서류
    REVISION = "revision"  # 기존 서류의 수정본

    LABELS = {NEW: "신규", REVISION: "수정"}


class ChangeKind:
    """작업지시서 7.3 — 변경 표시"""
    ADDED = "added"            # 신규 항목
    CHANGED = "changed"        # 값 변경
    MISSING = "missing"        # 기존 항목 미발견 (삭제로 확정하지 않는다)
    SAME = "same"              # 비교값 동일
    UNCERTAIN = "uncertain"    # 추출·대응 확인 필요

    LABELS = {
        ADDED: "신규 항목",
        CHANGED: "값 변경",
        MISSING: "기존 항목 미발견",
        SAME: "비교값 동일",
        UNCERTAIN: "추출·대응 확인 필요",
    }


# ─────────────────────────────────────────────────────────────
# 계정 / 직원
# ─────────────────────────────────────────────────────────────

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    display_name = db.Column(db.String(64), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="manager")  # admin | manager
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    @property
    def is_admin(self):
        return self.role == "admin"


class Employee(db.Model):
    __tablename__ = "employees"
    id = db.Column(db.Integer, primary_key=True)
    emp_no = db.Column(db.String(32), unique=True, nullable=False)
    name = db.Column(db.String(64), nullable=False)
    dept = db.Column(db.String(64))
    manager_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    manager = db.relationship("User", backref="employees")


# ─────────────────────────────────────────────────────────────
# 서류 묶음 / 파일 버전
# ─────────────────────────────────────────────────────────────

class DocumentGroup(db.Model):
    """같은 직원·귀속연도에 속하는 하나의 논리적 서류."""
    __tablename__ = "doc_groups"
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    tax_year = db.Column(db.Integer, nullable=False)
    doc_type = db.Column(db.String(16), nullable=False)
    display_name = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    # 현재 유효 버전 / 마지막으로 검토 완료된 버전
    current_version_id = db.Column(db.Integer)
    last_reviewed_version_id = db.Column(db.Integer)

    employee = db.relationship("Employee", backref="doc_groups")
    versions = db.relationship(
        "DocumentVersion",
        backref="group",
        order_by="DocumentVersion.seq",
        foreign_keys="DocumentVersion.group_id",
    )

    @property
    def version_list(self):
        """관계 캐시를 믿지 않고 직접 조회한다."""
        return (
            DocumentVersion.query.filter_by(group_id=self.id)
            .order_by(DocumentVersion.seq)
            .all()
        )

    @property
    def current_version(self):
        if self.current_version_id:
            v = db.session.get(DocumentVersion, self.current_version_id)
            if v is not None:
                return v
        vs = self.version_list
        return vs[-1] if vs else None

    @property
    def last_reviewed_version(self):
        if not self.last_reviewed_version_id:
            return None
        return db.session.get(DocumentVersion, self.last_reviewed_version_id)

    @property
    def review_state(self):
        """묶음의 업무 검토 상태 = 현재 버전의 상태."""
        cur = self.current_version
        if cur is None:
            return ReviewState.NEW
        return cur.review_state

    @property
    def doc_type_label(self):
        return DocType.LABELS.get(self.doc_type, self.doc_type)


class DocumentVersion(db.Model):
    __tablename__ = "doc_versions"
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("doc_groups.id"), nullable=False)
    prev_version_id = db.Column(db.Integer, db.ForeignKey("doc_versions.id"))
    seq = db.Column(db.Integer, nullable=False, default=1)  # 1 = 최초 제출

    stored_name = db.Column(db.String(128), nullable=False)  # 서버가 생성한 저장 이름
    orig_filename = db.Column(db.String(256), nullable=False)
    sha256 = db.Column(db.String(64), nullable=False, index=True)
    byte_size = db.Column(db.Integer, nullable=False)
    page_count = db.Column(db.Integer)

    submit_kind = db.Column(db.String(16), nullable=False, default=SubmitKind.NEW)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.now)

    # 원본 페이지를 한 장도 렌더링하지 못하면 앱에서 검토 완료 불가 (작업지시서 7.4)
    render_ok = db.Column(db.Boolean, default=False)
    load_error = db.Column(db.String(256))

    uploaded_by = db.relationship("User")
    runs = db.relationship(
        "ExtractionRun", backref="version", order_by="ExtractionRun.revision_no"
    )
    reviews = db.relationship("Review", backref="version", order_by="Review.created_at")

    @property
    def latest_run(self):
        # 관계 캐시를 믿지 않는다. 같은 세션에서 추출 직후 조회하면 비어 있을 수 있다.
        return (
            ExtractionRun.query.filter_by(version_id=self.id)
            .order_by(ExtractionRun.revision_no.desc())
            .first()
        )

    @property
    def is_reviewed(self):
        return (
            Review.query.filter_by(version_id=self.id, kind="complete").first()
            is not None
        )

    @property
    def review_state(self):
        """작업지시서 8장 상태 판정 규칙."""
        if self.is_reviewed:
            return ReviewState.DONE
        run = self.latest_run
        if run is None or run.status in (RunStatus.PENDING, RunStatus.RUNNING):
            return ReviewState.EXTRACT_CHECK
        # 읽기 실패·부분 성공이면 사람이 원본을 봐야 한다
        if run.status in (RunStatus.FAILED, RunStatus.PARTIAL):
            return ReviewState.EXTRACT_CHECK
        # 추출은 됐다 → 최초 제출이면 신규 검토, 수정본이면 재확인
        if self.seq == 1:
            return ReviewState.NEW
        return ReviewState.RECHECK

    @property
    def review_state_label(self):
        return ReviewState.LABELS.get(self.review_state, self.review_state)

    @property
    def label(self):
        return "최초 제출" if self.seq == 1 else f"수정 {self.seq - 1}차"


# ─────────────────────────────────────────────────────────────
# 추출
# ─────────────────────────────────────────────────────────────

class ExtractionRun(db.Model):
    """한 버전을 읽은 결과 판본. 재추출하면 revision_no 가 올라간다."""
    __tablename__ = "extraction_runs"
    id = db.Column(db.Integer, primary_key=True)
    version_id = db.Column(db.Integer, db.ForeignKey("doc_versions.id"), nullable=False)
    revision_no = db.Column(db.Integer, nullable=False, default=1)

    tool_version = db.Column(db.String(128))
    status = db.Column(db.String(16), nullable=False, default=RunStatus.PENDING)
    error = db.Column(db.Text)

    pages_total = db.Column(db.Integer, default=0)
    pages_text = db.Column(db.Integer, default=0)    # 텍스트로 읽은 페이지
    pages_ocr = db.Column(db.Integer, default=0)     # OCR로 읽은 페이지
    pages_failed = db.Column(db.Integer, default=0)  # 읽지 못한 페이지
    unsupported_form = db.Column(db.Boolean, default=False)

    started_at = db.Column(db.DateTime, default=datetime.now)
    finished_at = db.Column(db.DateTime)

    fields = db.relationship("ExtractedField", backref="run", order_by="ExtractedField.id")

    @property
    def status_label(self):
        return RunStatus.LABELS.get(self.status, self.status)

    @property
    def has_unread(self):
        return (self.pages_failed or 0) > 0 or bool(self.unsupported_form)


class ExtractedField(db.Model):
    __tablename__ = "extracted_fields"
    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey("extraction_runs.id"), nullable=False)

    subject = db.Column(db.String(64))      # 대상자 (본인/배우자/자녀 등). 모르면 None
    field_key = db.Column(db.String(128), nullable=False)  # 항목 연결 키
    field_label = db.Column(db.String(128), nullable=False)

    raw_value = db.Column(db.String(512))    # 원문 그대로
    norm_value = db.Column(db.String(512))   # 정규화한 값 (비교에 사용)
    value_kind = db.Column(db.String(16), default="text")  # text | amount | date

    page_no = db.Column(db.Integer)
    method = db.Column(db.String(16), default="text")  # text | ocr | manual
    confirm_state = db.Column(db.String(16), default="auto")  # auto | confirmed | corrected

    corrections = db.relationship("FieldCorrection", backref="field", order_by="FieldCorrection.created_at")

    @property
    def method_label(self):
        return {"text": "텍스트", "ocr": "OCR", "manual": "수동입력"}.get(self.method, self.method)

    @property
    def display_value(self):
        return self.norm_value if self.norm_value is not None else (self.raw_value or "")


class FieldCorrection(db.Model):
    """OCR 원문을 보존하면서 사람이 고친 값을 따로 남긴다."""
    __tablename__ = "field_corrections"
    id = db.Column(db.Integer, primary_key=True)
    field_id = db.Column(db.Integer, db.ForeignKey("extracted_fields.id"), nullable=False)
    old_value = db.Column(db.String(512))
    new_value = db.Column(db.String(512))
    reason = db.Column(db.String(256))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    user = db.relationship("User")


# ─────────────────────────────────────────────────────────────
# 비교 / 검토 / 감사
# ─────────────────────────────────────────────────────────────

class Comparison(db.Model):
    __tablename__ = "comparisons"
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("doc_groups.id"), nullable=False)
    base_version_id = db.Column(db.Integer)   # 비교 기준 (가장 최근 검토 완료 버전)
    base_run_id = db.Column(db.Integer)
    new_version_id = db.Column(db.Integer, nullable=False)
    new_run_id = db.Column(db.Integer)
    base_is_reviewed = db.Column(db.Boolean, default=False)  # False면 '최초 검토 미완료'
    result_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)


class Review(db.Model):
    """특정 버전 + 특정 추출 판본에 대한 확인 기록."""
    __tablename__ = "reviews"
    id = db.Column(db.Integer, primary_key=True)
    version_id = db.Column(db.Integer, db.ForeignKey("doc_versions.id"), nullable=False)
    run_id = db.Column(db.Integer)  # 확인 당시 사용한 추출 판본
    reviewer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    kind = db.Column(db.String(16), default="complete")  # complete | note
    note = db.Column(db.Text)
    manual_reason = db.Column(db.String(256))  # 추출 실패분을 원본으로 직접 봤을 때 사유
    created_at = db.Column(db.DateTime, default=datetime.now)

    reviewer = db.relationship("User")


class AuditEvent(db.Model):
    __tablename__ = "audit_events"
    id = db.Column(db.Integer, primary_key=True)
    target_type = db.Column(db.String(32))
    target_id = db.Column(db.Integer)
    action = db.Column(db.String(64), nullable=False)
    detail = db.Column(db.String(512))
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.now)

    actor = db.relationship("User")


def log(action, target_type=None, target_id=None, detail=None, actor=None):
    db.session.add(
        AuditEvent(
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            actor_id=actor.id if actor else None,
        )
    )
