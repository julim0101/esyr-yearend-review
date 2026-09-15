# ESYR · Etners Smart Year-end Review

**배포:** https://esyr-yearend-review.vercel.app
(Vercel + Supabase Postgres + Supabase Storage · 서울 리전)

연말정산 증빙 PDF의 **추가·수정 제출본**을 이전에 검토한 버전과 비교해,
무엇이 달라졌고 **무엇을 다시 확인해야 하는지**만 남기는 도구.

이미 확인한 자료의 검토 기록은 그대로 유지한다.

> 이 앱의 **검토 완료**는 담당자가 해당 자료 버전을 확인했다는 뜻이다.
> 세법상 공제 적격이나 연말정산 신고 완료를 의미하지 않는다.
> 공제 가능 여부·세액 계산·위변조 판정은 수행하지 않는다.

---

## 빠른 실행

```bash
pip install -r requirements.txt
python make_samples.py     # 시연용 가상 PDF 12종 생성
python seed.py --demo      # 계정·직원·시연 시나리오 등록
python run.py              # http://127.0.0.1:5000
```

Windows 는 `run.bat` 더블클릭.

**시연 계정** — `manager1 / esyr1234` (담당자) · `admin / esyr1234` (관리자)

---

## OCR 설치 (스캔 PDF를 읽으려면 필요)

`pytesseract` 는 파이썬 래퍼일 뿐이다. **엔진과 언어데이터는 별도 설치**해야 한다.

```powershell
# 1) 엔진
winget install UB-Mannheim.TesseractOCR

# 2) 한국어 언어데이터 (공백·한글 없는 경로여야 함)
$dst="$env:LOCALAPPDATA\esyr\tessdata"
New-Item -ItemType Directory -Force -Path $dst
foreach($l in @("kor","eng","osd")){
  Invoke-WebRequest "https://github.com/tesseract-ocr/tessdata_fast/raw/main/$l.traineddata" -OutFile "$dst\$l.traineddata"
}
```

확인: `http://127.0.0.1:5000/health` 또는 대시보드 상단 배너.

**OCR이 없어도 앱은 동작한다.** 다만 스캔 PDF는 값을 추측하지 않고
`추출 확인 필요` 로 남긴다. 가짜 값을 만들지 않는 것이 이 도구의 전제다.

---

## 지원 서식

| 서류 | 근거 서식 | 자동 추출 항목 |
|---|---|---|
| 기부금영수증 | 소득세법 시행규칙 [별지 제45호의2서식] (2022.3.18. 개정) | 일련번호, 기부자 성명·주소, 단체명·사업자등록번호, 근거법령, 기부내역(코드·연월일·품명·금액), 합계 |
| 간소화자료 | 「OOOO년 귀속 소득ㆍ세액공제증명서류 : 기본내역 [항목]」 | 귀속연도, 항목, 가입자 성명·주민등록번호, 월별 금액, 합계 |
| 기타 | — | 자동 추출 없음. 원본 조회 + 수동 검토 기록만 |

**가상 서식으로만 검증했다.** 홈택스 원본 전체 지원을 주장하지 않으며,
임의 기관의 모든 영수증 양식을 자동 처리하지 않는다.

---

## 설계에서 정한 것

- **비교 기준은 '가장 최근 검토 완료 버전'** 이다. 직전 제출본이 아니다.
  V1 완료 → V2 미검토 → V3 제출이면 기준은 V1이고 V2 이력도 남는다.
- **새 영수증은 새 서류 묶음**이 된다. 기존 영수증을 교체하지 않는다.
- **수정본은 사용자가 지정한 묶음**에만 붙는다. 파일명·OCR 성명으로 자동 연결하지 않는다.
- **읽지 못한 값을 0이나 빈 문자열로 바꾸지 않는다.** '변경 없음'으로 처리하지 않는다.
- **기존 항목이 안 보여도 삭제로 확정하지 않는다.** 추출 실패일 수 있다.
- **합계가 같아도 세부내역이 바뀌면 잡아낸다.**
- **파일이 달라지면 값이 같아도 자동 완료하지 않는다.**
- **원본을 한 장도 렌더링하지 못한 파일은 앱에서 완료할 수 없다.**
- 사람이 고친 값과 원래 추출 원문을 **둘 다 보존**한다.
- 급여·증빙 원본은 **서버 비공개 경로**에만 두고 인증된 경로로만 내보낸다.

---

## 검증

```bash
python verify.py
```

작업지시서 12장 체크리스트 16항목 자동 검증. 통과/실패를 그대로 출력한다.

수동 확인이 필요한 항목:
- 서버 재시작 후 데이터 유지
- 네트워크 차단 상태 동작 (외부 호출 코드 없음)

---

## 구조

```
esyr/
  models.py    서류묶음 / 파일버전 / 추출판본 / 검토기록 분리
  extract.py   PDF 텍스트·OCR 추출, 서식별 파서
  compare.py   버전 비교 엔진
  routes.py    화면·권한·CSV
  templates/   Jinja2
  static/      CSS, 이트너스 CI·페이롤 BI
make_samples.py  시연용 가상 PDF 생성
seed.py          초기 데이터
verify.py        검증 체크리스트
```

---

## 데이터 보관

- 로컬 SQLite (`instance/esyr.sqlite3`) 와 파일(`instance/storage/`)에 저장된다.
  브라우저를 닫아도 삭제되지 않는다.
- 저장소는 `.gitignore` 로 제외된다. 원본 PDF와 DB는 커밋되지 않는다.
- 시연 자료는 전부 **가상자료**다. 실제 국세청 발급 문서나 실제 단체의 증빙이 아니다.
- 실제 운영 시 보관·삭제 기간과 백업 정책은 별도로 정해야 한다.

---

## Vercel + Supabase 배포

로컬은 SQLite + 파일, 배포는 Supabase Postgres + Supabase Storage 를 쓴다.
같은 코드가 환경변수만 보고 갈라진다.

### 1. Supabase

1. 프로젝트 생성 → **Settings → Database → Connection string → URI** 복사
   (Connection pooling / **Transaction** 모드, 포트 `6543` 권장)
2. **Storage → New bucket** → 이름 `esyr-docs`, **Public 체크 해제**
3. **Settings → API → service_role** 키 복사 (비공개 키. 절대 커밋하지 않는다)

### 2. Vercel 환경변수

| 이름 | 값 |
|---|---|
| `DATABASE_URL` | `postgresql://postgres.xxxx:PASSWORD@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres` |
| `SUPABASE_URL` | `https://xxxx.supabase.co` |
| `SUPABASE_SERVICE_KEY` | `eyJ...` (service_role) |
| `SUPABASE_BUCKET` | `esyr-docs` |
| `ESYR_SECRET_KEY` | 임의의 64자 hex |

### 3. 테이블·계정 1회 생성

로컬에서 배포용 DB를 향해 실행한다.

```powershell
$env:DATABASE_URL="postgresql://..."
$env:SUPABASE_URL="https://xxxx.supabase.co"
$env:SUPABASE_SERVICE_KEY="eyJ..."
$env:SUPABASE_BUCKET="esyr-docs"
python init_db.py --demo
```

### 4. 배포

```bash
git push        # Vercel 이 GitHub 연결 후 자동 배포
```

### 배포 환경의 제약 — 발표에서 먼저 말할 것

| 항목 | 로컬 | Vercel |
|---|---|---|
| DB | SQLite | Supabase Postgres |
| 원본 PDF | `instance/storage/` | Supabase Storage (비공개 버킷) |
| **OCR (스캔 PDF)** | **동작** | **동작하지 않음** |

Vercel 서버리스에는 Tesseract 같은 **시스템 바이너리를 설치할 수 없다.**
그래서 배포본에서 스캔 PDF는 값을 추측하지 않고 `추출 확인 필요` 로 남는다.
이것은 고장이 아니라 **설계상 선택**이다 — 읽지 못한 것을 읽은 척하지 않는다.

OCR까지 포함해 운영하려면 컨테이너 기반(Render·Railway·사내 서버)에 올려야 한다.
