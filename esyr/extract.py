"""ESYR — PDF 읽기와 항목 추출

작업지시서 5장을 따른다.

원칙 (지키지 않으면 도구가 거짓말을 한다):
  · 글자가 몇 개 나온다고 페이지 전체를 정상 추출했다고 판단하지 않는다.
  · 읽지 못한 값을 0이나 빈 문자열로 바꾸지 않는다. 읽지 못했다고 기록한다.
  · OCR이 설치되어 있지 않으면 그 사실을 그대로 보고한다. 흉내내지 않는다.
  · 임의의 정확도 백분율을 만들어내지 않는다.
"""
import hashlib
import os
import re
import shutil
import unicodedata
from datetime import datetime

import fitz  # PyMuPDF

from .models import (
    DocType, ExtractedField, ExtractionRun, RunStatus, db,
)

# 페이지에 이 글자 수 미만이면 "텍스트 레이어가 없다"고 보고 OCR 대상으로 넘긴다.
TEXT_MIN_CHARS = 40

TOOL_VERSION = f"PyMuPDF {fitz.version[0]}"


# ─────────────────────────────────────────────────────────────
# OCR 준비 상태 — 있는 그대로 보고한다
# ─────────────────────────────────────────────────────────────

# 프로젝트 안에 넣어 둔 언어데이터를 우선 사용한다 (Program Files 쓰기 권한 불필요)
_PROJECT_TESSDATA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tessdata"
)

# Windows 기본 설치 경로 — PATH 에 없어도 찾는다
_TESS_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
]


def _find_tesseract():
    exe = shutil.which("tesseract")
    if exe:
        return exe
    for c in _TESS_CANDIDATES:
        if os.path.isfile(c):
            return c
    return None


def _prepare_ocr():
    """pytesseract 가 실행파일과 언어데이터를 찾도록 설정한다."""
    try:
        import pytesseract
    except ImportError:
        return None, (
            "pytesseract 가 설치되어 있지 않습니다. "
            "서버리스(Vercel) 배포본에서는 OCR 을 사용할 수 없습니다."
        )

    exe = _find_tesseract()
    if not exe:
        return None, (
            "Tesseract 실행파일을 찾지 못했습니다. "
            "pip 설치만으로는 준비되지 않습니다. "
            "Windows: winget install UB-Mannheim.TesseractOCR (README 참고)"
        )
    pytesseract.pytesseract.tesseract_cmd = exe

    # 언어데이터 위치 — 경로에 한글이 있으면 Tesseract 가 못 읽으므로 ASCII 경로를 우선한다
    for cand in _tessdata_candidates():
        if os.path.isfile(os.path.join(cand, "kor.traineddata")) and cand.isascii():
            os.environ["TESSDATA_PREFIX"] = cand
            break
    return pytesseract, None


def _tessdata_candidates():
    out = []
    env = os.environ.get("ESYR_TESSDATA")
    if env:
        out.append(env)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        out.append(os.path.join(local, "esyr", "tessdata"))
    out.append(_PROJECT_TESSDATA)
    out.append(r"C:\Program Files\Tesseract-OCR\tessdata")
    out.append("/usr/share/tesseract-ocr/5/tessdata")
    return out


def has_kor_data():
    """kor.traineddata 가 실제로 있는지 파일로 확인한다 (stdout 파싱에 의존하지 않는다)."""
    for cand in _tessdata_candidates():
        if os.path.isfile(os.path.join(cand, "kor.traineddata")):
            return True, cand
    return False, None


def ocr_config():
    """OCR 실행 시 넘길 추가 설정 (언어데이터 경로 지정).

    pytesseract 는 config 문자열을 split() 해서 인자로 넘기므로 따옴표를 붙이면 안 된다.
    공백이 든 경로는 그래서 쓸 수 없다 — ASCII·공백 없는 경로를 고른다.
    """
    p = os.environ.get("TESSDATA_PREFIX")
    if p and " " not in p:
        return f"--tessdata-dir {p}"
    return ""


def ocr_status():
    """Tesseract 실행파일과 한국어 언어데이터가 준비됐는지 확인한다.

    반환: (available: bool, detail: str)
    """
    pytesseract, err = _prepare_ocr()
    if err:
        return False, err

    ok, where = has_kor_data()
    if not ok:
        return False, (
            "Tesseract는 설치되어 있으나 한국어 언어데이터(kor.traineddata)가 없습니다. "
            "README의 언어데이터 설치 안내를 참고하세요."
        )
    return True, f"Tesseract 사용 가능 (kor+eng · 언어데이터: {where})"


# ─────────────────────────────────────────────────────────────
# 값 정규화 — 표현 차이만 제거한다. 값 자체를 만들어내지 않는다.
# ─────────────────────────────────────────────────────────────

def norm_text(s):
    if s is None:
        return None
    s = unicodedata.normalize("NFKC", str(s))
    s = re.sub(r"\s+", " ", s).strip()
    return s


def norm_amount(s):
    """'150,000원' → '150000'. 숫자를 못 찾으면 None (0으로 바꾸지 않는다)."""
    if s is None:
        return None
    t = unicodedata.normalize("NFKC", str(s))
    t = t.replace(",", "").replace(" ", "")
    m = re.search(r"(\d+)", t)
    if not m:
        return None
    return m.group(1)


def norm_date(s):
    """'2025.03.14' / '2025-03-14' / '2025년 3월 14일' → '2025-03-14'."""
    if s is None:
        return None
    t = unicodedata.normalize("NFKC", str(s))
    m = re.search(r"(\d{4})\s*[.\-년/]\s*(\d{1,2})\s*[.\-월/]\s*(\d{1,2})", t)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(\d{4})\s*[.\-년/]\s*(\d{1,2})", t)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    return norm_text(s)


NORMALIZERS = {"amount": norm_amount, "date": norm_date, "text": norm_text}


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ─────────────────────────────────────────────────────────────
# 페이지 읽기
# ─────────────────────────────────────────────────────────────

def read_pages(path, max_pages=50):
    """각 페이지를 텍스트 → (필요시) OCR 순으로 읽는다.

    반환: (pages, meta)
      pages: [{'no':1,'text':str|None,'method':'text'|'ocr'|None,'ok':bool,'note':str}]
      meta : {'page_count', 'encrypted', 'error', 'ocr_available', 'ocr_detail'}
    """
    meta = {
        "page_count": 0,
        "encrypted": False,
        "error": None,
        "ocr_available": False,
        "ocr_detail": "",
    }
    pages = []

    try:
        doc = fitz.open(path)
    except Exception as e:  # noqa: BLE001
        meta["error"] = f"PDF를 열 수 없습니다: {e}"
        return pages, meta

    if doc.needs_pass:
        meta["encrypted"] = True
        meta["error"] = "암호가 설정된 PDF입니다. 암호 해제 후 다시 제출해 주세요."
        doc.close()
        return pages, meta

    meta["page_count"] = doc.page_count
    ocr_ok, ocr_detail = ocr_status()
    meta["ocr_available"] = ocr_ok
    meta["ocr_detail"] = ocr_detail

    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        rec = {"no": i + 1, "text": None, "method": None, "ok": False, "note": ""}
        try:
            text = page.get_text("text") or ""
        except Exception as e:  # noqa: BLE001
            text = ""
            rec["note"] = f"텍스트 추출 오류: {e}"

        if len(text.strip()) >= TEXT_MIN_CHARS:
            rec.update(text=text, method="text", ok=True)
        else:
            # 텍스트 레이어가 없거나 빈약하다 → OCR 대상
            if ocr_ok:
                try:
                    from PIL import Image
                    import io as _io

                    pytesseract, _err = _prepare_ocr()
                    # 해상도를 올려야 한글 인식률이 확보된다
                    pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))
                    img = Image.open(_io.BytesIO(pix.tobytes("png")))
                    ocr_text = pytesseract.image_to_string(
                        img, lang="kor+eng", config=ocr_config()
                    )
                    if len(ocr_text.strip()) >= 10:
                        rec.update(text=ocr_text, method="ocr", ok=True)
                        rec["note"] = "스캔 페이지를 OCR로 읽었습니다."
                    else:
                        rec["note"] = "OCR을 실행했으나 읽을 수 있는 글자가 없습니다."
                except Exception as e:  # noqa: BLE001
                    rec["note"] = f"OCR 실행 실패: {e}"
            else:
                rec["note"] = (
                    "텍스트 레이어가 없는 스캔 페이지입니다. "
                    f"OCR을 사용할 수 없습니다 — {ocr_detail}"
                )
        pages.append(rec)

    if doc.page_count > max_pages:
        meta["error"] = f"페이지 수 제한({max_pages}p)을 초과했습니다. 앞 {max_pages}p만 읽었습니다."
    doc.close()
    return pages, meta


def render_page_png(path, page_no, zoom=2.0):
    """원본 페이지를 PNG 바이트로 렌더링. 실패하면 None."""
    try:
        doc = fitz.open(path)
        if doc.needs_pass or page_no < 1 or page_no > doc.page_count:
            doc.close()
            return None
        pix = doc[page_no - 1].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        data = pix.tobytes("png")
        doc.close()
        return data
    except Exception:  # noqa: BLE001
        return None


# ─────────────────────────────────────────────────────────────
# 지원 서식 파서
#   지원하는 것만 자동 추출한다. 못 알아보면 '미지원 서식'으로 남긴다.
# ─────────────────────────────────────────────────────────────

MONEY = r"([0-9][0-9,\.]*)\s*원?"


def parse_donation(pages):
    """기부금영수증 — 소득세법 시행규칙 [별지 제45호의2서식]

    실제 서식 구조:
      일련번호
      ① 기부자      : 성명(법인명) | 주민등록번호 / 주소(소재지)
      ② 기부금 단체  : 단체명 | 사업자등록번호 / 소재지 / 근거법령
      ③ 기부금 모집처(언론기관 등)
      ④ 기부내용     : 코드 | 구분 | 연월일 | 품명 | 수량 | 단가 | 금액

    반환: (fields, recognized)
    """
    full = "\n".join(p["text"] or "" for p in pages)
    if "기부금" not in full or ("영수증" not in full and "기부내용" not in full):
        return [], False

    fields = []

    def add(key, label, raw, page_no, method, kind="text", subject=None):
        fields.append(dict(
            subject=subject, field_key=key, field_label=label,
            raw_value=raw.strip(), value_kind=kind,
            page_no=page_no, method=method or "text",
        ))

    def grab(pattern, key, label, kind="text", flags=0):
        for p in pages:
            if not p["text"]:
                continue
            m = re.search(pattern, p["text"], flags)
            if m:
                add(key, label, m.group(1), p["no"], p["method"], kind)
                return True
        return False

    # 일련번호
    grab(r"일련번호\s*\n?\s*([0-9\-]{4,})", "serial", "일련번호")
    # ① 기부자 — 라벨 다음 줄에 값이 오는 표 구조
    grab(r"성명\(법인명\)\s*\n?\s*([^\n]+)", "donor_name", "기부자 성명")
    grab(r"주소\(소재지\)\s*\n?\s*([^\n]+)", "donor_addr", "기부자 주소")
    # ② 기부금 단체
    grab(r"단\s*체\s*명\s*\n?\s*([^\n]+)", "org", "기부금 단체명")
    grab(r"사업자등록번호\s*\n?\s*([0-9\-]{8,})", "org_bizno", "단체 사업자등록번호")
    grab(r"기부금단체\s*근거법령\s*\n?\s*([^\n]+)", "org_law", "근거법령")

    # ④ 기부내용 표 — 한 줄에 코드/구분/연월일/품명/수량/단가/금액
    total = 0
    n_detail = 0
    for p in pages:
        if not p["text"]:
            continue
        for m in re.finditer(
            r"^\s*(\d{2})\s+(금전|현물)\s+"
            r"(\d{4}[.\-]\d{1,2}[.\-]\d{1,2})\s+"
            r"(\S+)\s+(\d+)\s+([0-9,]+)\s+([0-9,]+)\s*$",
            p["text"], re.MULTILINE,
        ):
            code, gubun, date, item, qty, unit_price, amt = m.groups()
            n_detail += 1
            add(f"detail::{norm_date(date)}::{item}",
                f"기부내역 {date} {item}", amt, p["no"], p["method"], "amount")
            add(f"detail_code::{norm_date(date)}::{item}",
                f"기부내역 코드 {date} {item}", code, p["no"], p["method"])
            v = norm_amount(amt)
            if v:
                total += int(v)

    # 합계는 내역에서 계산한다 (별도 합계란이 없는 서식이므로)
    if n_detail:
        pg_no = next((p["no"] for p in pages if p["text"]), 1)
        mth = next((p["method"] for p in pages if p["text"]), "text")
        add("amount", "기부금액 합계", f"{total:,}", pg_no, mth, "amount")

    return fields, bool(fields)


SIMPL_CATEGORIES = [("의료비", "medical"), ("교육비", "education"), ("기부금", "donation")]


def parse_simplified(pages):
    """간소화자료 — 「OOOO년 귀속 소득ㆍ세액공제증명서류 : 기본내역 [항목]」

    실제 서식 구조:
      제목      : 2025년 귀속 소득ㆍ세액공제증명서류 : 기본내역 [의료비]
      조회기간  : 2025년 01 ~ 12월
      가입자 인적사항 : 성명 | 주민등록번호
      월별 내역표    : 월별 | 지출금액 | 공제대상금액  ... 합계

    이 서식은 '한 사람 한 항목'이 한 장이다. 그래도 가족 자료가 섞여 들어올 수 있으므로
    문서에 적힌 성명을 subject 로 기록하고, 업로드 직원 본인의 지출로 단정하지 않는다.
    """
    full = "\n".join(p["text"] or "" for p in pages)
    if "소득" not in full or "공제증명서류" not in full:
        return [], False

    fields = []

    def add(key, label, raw, page_no, method, kind="text", subject=None):
        fields.append(dict(
            subject=subject, field_key=key, field_label=label,
            raw_value=str(raw).strip(), value_kind=kind,
            page_no=page_no, method=method or "text",
        ))

    p1 = next((p for p in pages if p["text"]), None)
    if not p1:
        return [], False
    pno, mth = p1["no"], p1["method"]

    # 제목에서 귀속연도 · 항목
    category = None
    m = re.search(r"(\d{4})\s*년\s*귀속.*?기본내역\s*\[([^\]]+)\]", full, re.S)
    if m:
        add("tax_year", "귀속연도", m.group(1), pno, mth)
        category = m.group(2).strip()
        add("category", "증명서류 항목", category, pno, mth)

    # 가입자 성명 — '성 명' / '주민등록번호' 헤더 다음 줄
    subject = None
    ms = re.search(r"주\s*민\s*등\s*록\s*번\s*호\s*\n\s*([^\n]+?)\s*\n\s*(\d{6}-\d\*+|\d{6}-\d{7})", full)
    if ms:
        subject = ms.group(1).strip()
        add("holder_name", "가입자 성명", subject, pno, mth)
        add("holder_rrn", "가입자 주민등록번호", ms.group(2), pno, mth)

    if not category:
        return fields, bool(fields)

    # 월별 내역 — "01월  84,000  84,000"
    for p in pages:
        if not p["text"]:
            continue
        for mm in re.finditer(r"^\s*(\d{2})월\s+([0-9,]+)\s+([0-9,]+)\s*$",
                              p["text"], re.MULTILINE):
            month, spend, deductible = mm.groups()
            if norm_amount(spend) == "0" and norm_amount(deductible) == "0":
                continue  # 0원 달은 비교 노이즈만 만든다
            add(f"{category}::{subject or 'unknown'}::{month}월",
                f"{category} {month}월" + (f" ({subject})" if subject else " (대상자 미확인)"),
                spend, p["no"], p["method"], "amount", subject)

    # 합계
    for p in pages:
        if not p["text"]:
            continue
        mt = re.search(r"^\s*합계\s+([0-9,]+)\s+([0-9,]+)\s*$", p["text"], re.MULTILINE)
        if mt:
            add(f"{category}::{subject or 'unknown'}::합계",
                f"{category} 합계" + (f" ({subject})" if subject else ""),
                mt.group(1), p["no"], p["method"], "amount", subject)
            break

    return fields, bool(fields)


PARSERS = {DocType.SIMPLIFIED: parse_simplified, DocType.DONATION: parse_donation}


# ─────────────────────────────────────────────────────────────
# 추출 실행
# ─────────────────────────────────────────────────────────────

def run_extraction(version, abs_path):
    """한 파일 버전을 읽어 ExtractionRun + ExtractedField 를 만든다."""
    prev = len(version.runs)
    run = ExtractionRun(
        version_id=version.id,
        revision_no=prev + 1,
        tool_version=TOOL_VERSION,
        status=RunStatus.RUNNING,
        started_at=datetime.now(),
    )
    db.session.add(run)
    db.session.flush()

    pages, meta = read_pages(abs_path)

    run.pages_total = meta["page_count"]
    version.page_count = meta["page_count"]
    version.render_ok = bool(render_page_png(abs_path, 1)) if meta["page_count"] else False

    if meta["error"] and not pages:
        run.status = RunStatus.FAILED
        run.error = meta["error"]
        version.load_error = meta["error"]
        run.finished_at = datetime.now()
        db.session.flush()
        return run

    run.pages_text = sum(1 for p in pages if p["method"] == "text")
    run.pages_ocr = sum(1 for p in pages if p["method"] == "ocr")
    run.pages_failed = sum(1 for p in pages if not p["ok"])

    parser = PARSERS.get(version.group.doc_type)
    fields, recognized = ([], False)
    if parser:
        fields, recognized = parser(pages)
    run.unsupported_form = not recognized

    for f in fields:
        normalizer = NORMALIZERS.get(f["value_kind"], norm_text)
        db.session.add(
            ExtractedField(
                run_id=run.id,
                subject=f.get("subject"),
                field_key=f["field_key"],
                field_label=f["field_label"],
                raw_value=f["raw_value"],
                norm_value=normalizer(f["raw_value"]),
                value_kind=f["value_kind"],
                page_no=f["page_no"],
                method=f["method"],
            )
        )

    notes = [f"{p['no']}p: {p['note']}" for p in pages if p["note"]]
    if meta["error"]:
        notes.insert(0, meta["error"])
    if run.unsupported_form:
        notes.append("자동 추출을 지원하지 않는 서식입니다. 원본을 직접 확인해 주세요.")
    run.error = "\n".join(notes) if notes else None

    # 상태 판정 — 하나라도 못 읽었으면 '성공'이라고 하지 않는다
    if run.pages_failed == 0 and recognized:
        run.status = RunStatus.SUCCESS
    elif run.pages_failed == run.pages_total and run.pages_total > 0:
        run.status = RunStatus.FAILED
    else:
        run.status = RunStatus.PARTIAL

    run.finished_at = datetime.now()
    db.session.flush()
    return run
