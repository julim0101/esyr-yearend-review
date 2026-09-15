"""ESYR — 시연용 가상 PDF 생성 (실제 서식 구조 반영)

  · 기부금영수증  : 소득세법 시행규칙 [별지 제45호의2서식] (2022.3.18. 개정)
  · 간소화자료    : 「OOOO년 귀속 소득·세액공제증명서류: 기본내역 [항목]」
  · 사찰등록증    : 종교단체 기부금 첨부서류 (이미지 기반 → OCR 대상)

전부 가상자료다. 실제 국세청 발급 문서나 실제 단체의 증빙이 아니다.

  python make_samples.py
"""
import os
import sys

import fitz

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")

FONT_CANDIDATES = [r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\gulim.ttc"]
FONT = next((f for f in FONT_CANDIDATES if os.path.exists(f)), None)
FN = "KO"

W, H = 595, 842          # A4
L, R = 45, 550           # 좌우 여백
GRAY = (0.45, 0.45, 0.45)
BLACK = (0.08, 0.08, 0.08)


def new_page(doc):
    pg = doc.new_page(width=W, height=H)
    if FONT:
        pg.insert_font(fontname=FN, fontfile=FONT)
    return pg


def txt(pg, x, y, s, size=9, color=BLACK, font=None):
    pg.insert_text((x, y), s, fontname=(font or (FN if FONT else "helv")),
                   fontsize=size, color=color)


def box(pg, x0, y0, x1, y1, width=0.7, color=BLACK):
    pg.draw_rect(fitz.Rect(x0, y0, x1, y1), color=color, width=width)


def hline(pg, x0, x1, y, width=0.7, color=BLACK):
    pg.draw_line(fitz.Point(x0, y), fitz.Point(x1, y), color=color, width=width)


def vline(pg, x, y0, y1, width=0.7, color=BLACK):
    pg.draw_line(fitz.Point(x, y0), fitz.Point(x, y1), color=color, width=width)


def watermark(pg):
    txt(pg, W - 165, 30, "시연용 가상자료 (실제 증빙 아님)", 7.5, GRAY)


# ══════════════════════════════════════════════════════════
# 기부금영수증 — 별지 제45호의2서식
# ══════════════════════════════════════════════════════════

def donation_receipt(serial, donor, donor_rrn, donor_addr,
                     org, org_bizno, org_addr, org_law,
                     rows, issue_date="2026년 01월 05일", code="40"):
    """rows: [(코드, 구분, 연월일, 품명, 수량, 단가, 금액), ...]"""
    doc = fitz.open()
    pg = new_page(doc)
    watermark(pg)

    y = 52
    txt(pg, L, y, "[별지 제45호의2서식]  (2022. 3. 18. 개정)", 7.5, GRAY)
    y += 6
    # 일련번호 박스
    box(pg, L, y, L + 150, y + 22)
    vline(pg, L + 58, y, y + 22)
    txt(pg, L + 12, y + 15, "일련번호", 8)
    txt(pg, L + 68, y + 15, serial, 8.5)
    # 제목
    txt(pg, 236, y + 17, "기 부 금 영 수 증", 16)
    y += 30
    txt(pg, L, y, "※ 뒤쪽의 작성방법을 읽고 작성하여 주시기 바랍니다.", 7.5, GRAY)
    txt(pg, R - 26, y, "(앞쪽)", 7.5, GRAY)
    y += 12

    def section(title):
        nonlocal y
        txt(pg, L, y + 9, title, 9.5)
        y += 14

    def row2(label_l, val_l, label_r, val_r, h=20):
        """좌: 라벨|값,  우: 라벨|값"""
        nonlocal y
        mid = 300
        box(pg, L, y, R, y + h)
        vline(pg, L + 95, y, y + h)
        vline(pg, mid, y, y + h)
        vline(pg, mid + 105, y, y + h)
        txt(pg, L + 6, y + h / 2 + 3, label_l, 8)
        txt(pg, L + 101, y + h / 2 + 3, val_l, 8.5)
        txt(pg, mid + 6, y + h / 2 + 3, label_r, 8)
        txt(pg, mid + 111, y + h / 2 + 3, val_r, 8.5)
        y += h

    def row1(label, val, h=20):
        nonlocal y
        box(pg, L, y, R, y + h)
        vline(pg, L + 95, y, y + h)
        parts = label.split("\n")
        if len(parts) == 1:
            txt(pg, L + 6, y + h / 2 + 3, label, 8)
        else:
            for j, pt in enumerate(parts):
                txt(pg, L + 6, y + h / 2 - 2 + j * 9, pt, 7.2)
        txt(pg, L + 101, y + h / 2 + 3, val, 8.5)
        y += h

    # ❶ 기부자
    section("① 기부자")
    row2("성명(법인명)", donor, "주민등록번호", donor_rrn)
    row1("주소(소재지)", donor_addr)
    y += 8

    # ❷ 기부금 단체
    section("② 기부금 단체")
    row2("단 체 명", org, "사업자등록번호", org_bizno)
    row1("소 재 지", org_addr)
    row1("기부금공제대상\n기부금단체 근거법령", org_law, h=26)
    y += 8

    # ❸ 기부금 모집처
    section("③ 기부금 모집처(언론기관 등)")
    row2("단 체 명", "", "사업자등록번호", "")
    row1("소 재 지", "")
    y += 8

    # ❹ 기부내용
    section("④ 기부내용")
    ch = 30
    cols = [L, L + 55, L + 120, L + 195, L + 300, L + 355, L + 420, R]
    heads = ["코 드", "구 분\n(금전 또는 현물)", "연월일", "품명", "수량", "단가", "금 액"]
    box(pg, L, y, R, y + ch)
    for cx in cols[1:-1]:
        vline(pg, cx, y, y + ch)
    # '내용' 병합 헤더
    hline(pg, cols[3], cols[6], y + 14)
    txt(pg, (cols[3] + cols[6]) / 2 - 12, y + 10, "내 용", 8)
    for i, hd in enumerate(heads):
        cx = (cols[i] + cols[i + 1]) / 2
        if i < 3:
            for j, part in enumerate(hd.split("\n")):
                txt(pg, cx - len(part) * 2.6, y + (13 if len(hd.split("\n")) == 1 else 11) + j * 8,
                    part, 7.5 if j else 8)
        elif i == 6:
            txt(pg, cx - 10, y + 20, hd, 8)
        else:
            txt(pg, cx - len(hd) * 2.6, y + 25, hd, 8)
    y += ch

    for r in rows:
        rh = 19
        box(pg, L, y, R, y + rh)
        for cx in cols[1:-1]:
            vline(pg, cx, y, y + rh)
        vals = [r[0], r[1], r[2], r[3], r[4], r[5], r[6]]
        for i, v in enumerate(vals):
            if i == 6:
                txt(pg, cols[7] - 8 - len(v) * 4.6, y + 13, v, 8.5)
            else:
                txt(pg, cols[i] + 5, y + 13, str(v), 8)
        y += rh

    y += 16
    txt(pg, L, y, "「소득세법」 제34조, 「조세특례제한법」 제76조ㆍ제88조의4 및 「법인세법」 제24조에 따른", 8)
    txt(pg, L, y + 12, "기부금을 위와 같이 기부하였음을 증명하여 주시기 바랍니다.", 8)
    y += 34
    txt(pg, 360, y, issue_date, 9)
    y += 20
    txt(pg, 360, y, "신청인          " + donor + "  (서명 또는 인)", 8.5)
    y += 22
    txt(pg, L, y, "위와 같이 기부금을 기부받았음을 증명합니다.", 8)
    y += 20
    txt(pg, 360, y, "기부금 수령인   " + org + "  (인)", 8.5)
    return doc


# ══════════════════════════════════════════════════════════
# 간소화자료 — 소득·세액공제증명서류: 기본내역
# ══════════════════════════════════════════════════════════

def simplified_doc(year, category, name, rrn, monthly, unit="(단위:원)",
                   col_heads=None, period=None):
    """monthly: [(월, 값1, 값2), ...]"""
    doc = fitz.open()
    pg = new_page(doc)
    watermark(pg)

    # 좌상단 마감증 도장 느낌
    pg.draw_rect(fitz.Rect(L, 40, L + 62, 78), color=(0.35, 0.55, 0.35), width=1.1)
    txt(pg, L + 8, 55, "정보확인필", 7, (0.3, 0.5, 0.3))
    txt(pg, L + 12, 68, "마감증", 8.5, (0.3, 0.5, 0.3))

    y = 108
    title = f"{year}년 귀속 소득ㆍ세액공제증명서류 : 기본내역 [{category}]"
    txt(pg, (W - len(title) * 6.2) / 2, y, title, 13)
    y += 18
    sub = f"(조회기간: {period or f'{year}년 01 ~ 12월'})"
    txt(pg, (W - len(sub) * 4.6) / 2, y, sub, 8.5, GRAY)
    y += 34

    txt(pg, L, y, "■ 가입자 인적사항", 9.5)
    y += 8
    box(pg, L, y, R, y + 38)
    vline(pg, (L + R) / 2, y, y + 38)
    hline(pg, L, R, y + 19)
    txt(pg, (L + (L + R) / 2) / 2 - 14, y + 13, "성    명", 8.5)
    txt(pg, ((L + R) / 2 + R) / 2 - 28, y + 13, "주 민 등 록 번 호", 8.5)
    txt(pg, (L + (L + R) / 2) / 2 - 12, y + 32, name, 9)
    txt(pg, ((L + R) / 2 + R) / 2 - 30, y + 32, rrn, 9)
    y += 54

    txt(pg, L, y, f"■ {category} 내역", 9.5)
    txt(pg, R - 42, y, unit, 7.5, GRAY)
    y += 8

    heads = col_heads or ["지출금액", "공제대상금액"]
    cols = [L, L + 70]
    seg = (R - (L + 70)) / len(heads)
    for i in range(len(heads)):
        cols.append(L + 70 + seg * (i + 1))

    hh = 24
    box(pg, L, y, R, y + hh)
    for cx in cols[1:-1]:
        vline(pg, cx, y, y + hh)
    txt(pg, L + 22, y + 15, "월별", 8.5)
    for i, hd in enumerate(heads):
        cx = (cols[i + 1] + cols[i + 2]) / 2
        txt(pg, cx - len(hd) * 2.7, y + 15, hd, 8.5)
    y += hh

    total = [0] * len(heads)
    for m in monthly:
        rh = 17
        box(pg, L, y, R, y + rh)
        for cx in cols[1:-1]:
            vline(pg, cx, y, y + rh)
        txt(pg, L + 20, y + 12, m[0], 8)
        for i, v in enumerate(m[1:]):
            s = f"{v:,}" if isinstance(v, int) else str(v)
            if isinstance(v, int):
                total[i] += v
            txt(pg, cols[i + 2] - 8 - len(s) * 4.4, y + 12, s, 8)
        y += rh

    # 합계
    rh = 19
    box(pg, L, y, R, y + rh, width=1.1)
    for cx in cols[1:-1]:
        vline(pg, cx, y, y + rh)
    txt(pg, L + 22, y + 13, "합계", 8.5)
    for i, v in enumerate(total):
        s = f"{v:,}"
        txt(pg, cols[i + 2] - 8 - len(s) * 4.4, y + 13, s, 8.5)
    y += rh + 22

    txt(pg, L, y, "· 본 증명서류는 시연을 위해 생성한 가상자료이며 국세청이 발급한 자료가 아닙니다.", 7.5, GRAY)
    txt(pg, L, y + 11, "· 간소화 자료는 공제요건 충족 여부가 검증되지 않은 자료입니다.", 7.5, GRAY)
    return doc


# ══════════════════════════════════════════════════════════
# 사찰등록증 — 이미지 기반 첨부서류
# ══════════════════════════════════════════════════════════

def temple_cert():
    doc = fitz.open()
    pg = new_page(doc)
    watermark(pg)
    cx = W / 2
    pg.draw_rect(fitz.Rect(70, 90, W - 70, 700), color=(0.55, 0.15, 0.15), width=2.2)
    pg.draw_rect(fitz.Rect(78, 98, W - 78, 692), color=(0.75, 0.45, 0.45), width=0.8)
    txt(pg, cx - 62, 175, "사 찰 등 록 증", 24, (0.25, 0.12, 0.12))
    txt(pg, cx - 78, 215, "단체 등록번호  366441-00088", 9, GRAY)
    txt(pg, cx - 84, 232, "사단법인 등록번호  205421-0000530", 9, GRAY)
    items = [
        ("1. 등 록 번 호", "증 제 2016 - 0001호"),
        ("2. 명       칭", "(사)대한불교조계종재단 연화사"),
        ("3. 소 재 지", "서울특별시 종로구 삼봉로 95"),
        ("4. 주지성명", "박 재 선 (거 목)"),
        ("5. 창건년월일", "2016년 03월 23일"),
    ]
    y = 290
    for k, v in items:
        txt(pg, 130, y, k, 11)
        txt(pg, 255, y, v, 11)
        y += 36
    txt(pg, cx - 96, y + 26, "위와 같이 종헌에 의거하여 등록하였음을 증명함.", 10.5)
    txt(pg, cx - 62, y + 82, "불기 2560년 06월 01일", 10.5)
    txt(pg, cx - 96, y + 130, "大韓佛敎曹溪宗 改革會議", 17, (0.25, 0.12, 0.12))
    txt(pg, cx - 54, y + 158, "總務院長   釋 巨 木", 10.5)
    return doc


def save(doc, name):
    path = os.path.join(OUT, name)
    doc.save(path)
    doc.close()
    print("  ", name)
    return path


def rasterize(src, dst, zoom=1.5):
    s = fitz.open(src)
    out = fitz.open()
    for p in s:
        pix = p.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        np = out.new_page(width=p.rect.width, height=p.rect.height)
        np.insert_image(np.rect, stream=pix.tobytes("png"))
    s.close()
    out.save(dst)
    out.close()
    print("  ", os.path.basename(dst), "(스캔본 · 텍스트 레이어 없음)")


# ══════════════════════════════════════════════════════════

DONOR = ("김하늘", "901231-1******", "서울특별시 성동구 왕십리로 100, 101동 1004호")
ORG_A = ("사단법인 행복나눔재단", "101-82-05814", "서울특별시 종로구 삼봉로 95 대성스카이렉스 101동 406호",
         "「법인세법 시행령」 제39조제1항제1호바목")
ORG_B = ("재단법인 푸른숲복지회", "214-82-01977", "경기도 성남시 분당구 판교로 235",
         "「소득세법 시행령」 제80조제1항제2호나목")
ORG_C = ("(사)대한불교조계종재단 연화사", "366441-00088", "서울특별시 종로구 삼봉로 95",
         "「소득세법 시행령」 제80조제1항제1호")


def main():
    os.makedirs(OUT, exist_ok=True)
    print("실제 서식 기반 가상 PDF 생성 →", OUT)

    # ── 기부금영수증: 금액 변경 (100,000 → 150,000) ──────────
    save(donation_receipt("2025-000412", *DONOR, *ORG_A,
                          [("40", "금전", "2025.03.14", "후원금", "1", "100,000", "100,000")]),
         "01_기부금영수증_행복나눔_최초.pdf")
    save(donation_receipt("2025-000412", *DONOR, *ORG_A,
                          [("40", "금전", "2025.03.14", "후원금", "1", "150,000", "150,000")]),
         "02_기부금영수증_행복나눔_수정_금액변경.pdf")

    # ── 같은 영수증의 스캔본 (OCR 필요) ──────────────────────
    tmp = save(donation_receipt("2025-000412", *DONOR, *ORG_A,
                                [("40", "금전", "2025.03.14", "후원금", "1", "150,000", "150,000")]),
               "_tmp_scan.pdf")
    rasterize(tmp, os.path.join(OUT, "03_기부금영수증_행복나눔_스캔본.pdf"))
    os.remove(tmp)

    # ── 신규 기관 추가 ────────────────────────────────────
    save(donation_receipt("2025-000088", *DONOR, *ORG_B,
                          [("40", "금전", "2025.06.02", "정기후원", "1", "80,000", "80,000")]),
         "04_기부금영수증_푸른숲_신규추가.pdf")

    # ── 합계는 같고 내역만 변경 ────────────────────────────
    save(donation_receipt("2025-000011", *DONOR, *ORG_C,
                          [("41", "금전", "2025.05.10", "정기법보시", "1", "200,000", "200,000"),
                           ("41", "금전", "2025.05.10", "일시법보시", "1", "100,000", "100,000")],
                          code="41"),
         "05_기부금영수증_연화사_최초.pdf")
    save(donation_receipt("2025-000011", *DONOR, *ORG_C,
                          [("41", "금전", "2025.05.10", "정기법보시", "1", "150,000", "150,000"),
                           ("41", "금전", "2025.05.10", "일시법보시", "1", "150,000", "150,000")],
                          code="41"),
         "06_기부금영수증_연화사_합계같고_내역변경.pdf")

    # ── 간소화자료 (의료비) 최초 / 수정 ─────────────────────
    med1 = [(f"{m:02d}월", v, v) for m, v in
            [(1, 84000), (2, 0), (3, 235000), (4, 0), (5, 120000), (6, 0),
             (7, 310000), (8, 0), (9, 91000), (10, 0), (11, 400000), (12, 0)]]
    med2 = [(f"{m:02d}월", v, v) for m, v in
            [(1, 84000), (2, 0), (3, 235000), (4, 0), (5, 120000), (6, 0),
             (7, 310000), (8, 0), (9, 91000), (10, 340000), (11, 400000), (12, 0)]]
    save(simplified_doc(2025, "의료비", DONOR[0], DONOR[1], med1,
                        col_heads=["지출금액", "공제대상금액"]),
         "07_간소화자료_의료비_최초.pdf")
    save(simplified_doc(2025, "의료비", DONOR[0], DONOR[1], med2,
                        col_heads=["지출금액", "공제대상금액"]),
         "08_간소화자료_의료비_수정.pdf")

    # ── 사찰등록증 (미지원 서식) ───────────────────────────
    tmp = save(temple_cert(), "_tmp_temple.pdf")
    rasterize(tmp, os.path.join(OUT, "09_사찰등록증_첨부서류.pdf"))
    os.remove(tmp)

    # ── 읽기 실패 사례 ────────────────────────────────────
    d = fitz.open()
    new_page(d)
    p2 = new_page(d)
    txt(p2, 200, 400, "(인쇄 상태 불량 · 판독 불가)", 11, GRAY)
    tmpb = os.path.join(OUT, "_tmp_blank.pdf")
    d.save(tmpb); d.close()
    rasterize(tmpb, os.path.join(OUT, "10_읽기실패_빈페이지포함_스캔.pdf"))
    os.remove(tmpb)

    # ── 암호화 / 손상 ─────────────────────────────────────
    doc = donation_receipt("2025-000999", *DONOR, *ORG_A,
                           [("40", "금전", "2025.07.01", "후원금", "1", "50,000", "50,000")])
    doc.save(os.path.join(OUT, "11_암호화_PDF.pdf"),
             encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="1234", owner_pw="1234")
    doc.close()
    print("   11_암호화_PDF.pdf (암호 1234)")

    with open(os.path.join(OUT, "12_손상된_PDF.pdf"), "wb") as f:
        f.write("%PDF-1.7\n일부러 깨뜨린 시연용 파일입니다.\n".encode("utf-8"))
    print("   12_손상된_PDF.pdf")

    print("\n완료. 모든 파일은 가상자료입니다.")
    if not FONT:
        print("경고: 한글 글꼴을 찾지 못했습니다.", file=sys.stderr)


if __name__ == "__main__":
    main()
