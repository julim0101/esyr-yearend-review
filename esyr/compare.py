"""ESYR — 수정본 비교

작업지시서 7장을 따른다.

비교 기준:
  · 기본은 그 서류 묶음의 '가장 최근 검토 완료 버전'이다. 직전 제출본이 아니다.
  · 검토 완료 버전이 없으면 직전 제출본과 비교하되 '최초 검토 미완료'를 유지한다.
  · V1 완료 → V2 미검토 → V3 제출이면 기준은 V1이다. (V2 기록은 남는다)

판정 원칙:
  · 금액이 같다는 이유만으로 같은 항목으로 연결하지 않는다. 식별정보로 연결한다.
  · 기존 항목이 안 보인다고 '삭제'로 확정하지 않는다. 추출 실패일 수 있다.
  · 읽지 못한 값을 0이나 빈 문자열로 바꿔 '변경 없음'으로 만들지 않는다.
  · 합계가 같아도 세부내역이 바뀌었으면 잡아낸다.
"""
import json

from .models import (
    ChangeKind, Comparison, DocumentVersion, ExtractionRun, RunStatus, db,
)


def pick_base_version(group, new_version):
    """비교 기준 버전을 고른다.

    반환: (base_version | None, base_is_reviewed: bool)
    """
    candidates = [
        v for v in group.version_list
        if v.id != new_version.id and v.seq < new_version.seq
    ]
    if not candidates:
        return None, False

    from .models import Review
    reviewed_ids = {
        r.version_id
        for r in Review.query.filter(
            Review.version_id.in_([v.id for v in candidates]),
            Review.kind == "complete",
        ).all()
    }
    reviewed = [v for v in candidates if v.id in reviewed_ids]
    if reviewed:
        return max(reviewed, key=lambda v: v.seq), True

    # 검토 완료된 버전이 없다 → 직전 제출본과 비교하되 '최초 검토 미완료'
    return max(candidates, key=lambda v: v.seq), False


def latest_run_of(version):
    """관계 캐시를 믿지 않고 직접 조회한다.

    같은 세션 안에서 추출 직후 비교하면 version.runs 가 갱신 전 값을 들고 있을 수 있다.
    """
    if version is None:
        return None
    return (
        ExtractionRun.query.filter_by(version_id=version.id)
        .order_by(ExtractionRun.revision_no.desc())
        .first()
    )


def _fields_of(run):
    """추출 판본의 항목을 {field_key: field} 로. 사람이 고친 값이 있으면 그 값을 쓴다."""
    if run is None:
        return {}
    from .models import ExtractedField
    out = {}
    for f in ExtractedField.query.filter_by(run_id=run.id).all():
        out[f.field_key] = f
    return out


def compare_versions(group, new_version):
    """새 버전을 기준 버전과 비교해 Comparison 을 만든다."""
    base_version, base_reviewed = pick_base_version(group, new_version)

    new_run = latest_run_of(new_version)
    base_run = latest_run_of(base_version)

    new_fields = _fields_of(new_run)
    base_fields = _fields_of(base_run)

    rows = []

    # 읽기 자체가 불완전하면, 비교 결과 전체를 신뢰할 수 없다고 먼저 알린다
    unreliable = []
    if new_run is None:
        unreliable.append("새 버전의 추출 결과가 없습니다.")
    else:
        if new_run.status == RunStatus.FAILED:
            unreliable.append("새 버전을 읽지 못했습니다. 원본을 직접 확인해야 합니다.")
        elif new_run.status == RunStatus.PARTIAL:
            unreliable.append(
                f"새 버전에서 읽지 못한 페이지가 있습니다 "
                f"(실패 {new_run.pages_failed}p / 전체 {new_run.pages_total}p). "
                "아래 비교 결과만으로 변경 없음을 판단하지 마세요."
            )
        if new_run.unsupported_form:
            unreliable.append("새 버전은 자동 추출을 지원하지 않는 서식입니다.")
    if base_run is not None and base_run.status in (RunStatus.PARTIAL, RunStatus.FAILED):
        unreliable.append("비교 기준 버전도 일부만 읽혔습니다. 누락 항목이 있을 수 있습니다.")

    all_keys = sorted(set(base_fields) | set(new_fields))
    for key in all_keys:
        b = base_fields.get(key)
        n = new_fields.get(key)

        if b is None and n is not None:
            kind = ChangeKind.ADDED
        elif b is not None and n is None:
            # 삭제로 확정하지 않는다
            kind = ChangeKind.MISSING
        else:
            bv, nv = b.display_value, n.display_value
            if bv is None or nv is None or bv == "" or nv == "":
                kind = ChangeKind.UNCERTAIN
            elif bv == nv:
                kind = ChangeKind.SAME
            else:
                kind = ChangeKind.CHANGED

        ref = n or b
        rows.append(
            dict(
                key=key,
                label=ref.field_label,
                subject=ref.subject,
                old=b.display_value if b else None,
                new=n.display_value if n else None,
                old_page=b.page_no if b else None,
                new_page=n.page_no if n else None,
                method=(n.method if n else (b.method if b else None)),
                kind=kind,
                kind_label=ChangeKind.LABELS[kind],
            )
        )

    # 합계는 같은데 내역이 바뀐 경우를 놓치지 않도록, 내역 변경이 있으면 표시
    detail_changed = any(
        r["key"].startswith("detail::") and r["kind"] in (ChangeKind.ADDED, ChangeKind.CHANGED, ChangeKind.MISSING)
        for r in rows
    )
    total_same = any(
        r["key"] == "amount" and r["kind"] == ChangeKind.SAME for r in rows
    )
    if detail_changed and total_same:
        unreliable.append("합계 금액은 같지만 세부내역이 달라졌습니다. 내역을 확인하세요.")

    summary = {k: 0 for k in ChangeKind.LABELS}
    for r in rows:
        summary[r["kind"]] += 1

    result = dict(rows=rows, summary=summary, warnings=unreliable)

    cmp_ = Comparison(
        group_id=group.id,
        base_version_id=base_version.id if base_version else None,
        base_run_id=base_run.id if base_run else None,
        new_version_id=new_version.id,
        new_run_id=new_run.id if new_run else None,
        base_is_reviewed=base_reviewed,
        result_json=json.dumps(result, ensure_ascii=False),
    )
    db.session.add(cmp_)
    db.session.flush()
    return cmp_, result


def load_result(cmp_):
    if not cmp_ or not cmp_.result_json:
        return dict(rows=[], summary={}, warnings=[])
    return json.loads(cmp_.result_json)


def latest_comparison(group, version):
    return (
        Comparison.query.filter_by(group_id=group.id, new_version_id=version.id)
        .order_by(Comparison.id.desc())
        .first()
    )


def change_summary_text(result):
    """CSV·목록에 넣을 짧은 변경 요약."""
    s = result.get("summary", {})
    parts = []
    for k in (ChangeKind.CHANGED, ChangeKind.ADDED, ChangeKind.MISSING, ChangeKind.UNCERTAIN):
        if s.get(k):
            parts.append(f"{ChangeKind.LABELS[k]} {s[k]}")
    return " · ".join(parts) if parts else "변경 후보 없음"
