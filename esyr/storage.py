"""ESYR — 원본 PDF 저장소

로컬 실행과 서버리스(Vercel) 배포를 같은 코드로 쓰기 위해 저장소를 분리한다.

  local     : instance/storage/ 에 파일로 (기본, 개발·사내망)
  supabase  : Supabase Storage 비공개 버킷에 (Vercel 배포)

서버리스는 파일시스템이 휘발되므로 로컬 저장을 쓸 수 없다.
어느 쪽이든 원본은 공개 경로에 두지 않고, 권한 확인 후 앱이 직접 내보낸다.
"""
import os
import tempfile

_BACKEND = None
_CONF = {}


def init_app(app):
    """앱 설정에서 저장소 종류를 정한다."""
    global _BACKEND, _CONF
    url = app.config.get("SUPABASE_URL")
    key = app.config.get("SUPABASE_SERVICE_KEY")
    bucket = app.config.get("SUPABASE_BUCKET")

    if url and key and bucket:
        _BACKEND = "supabase"
        _CONF = {"url": url.rstrip("/"), "key": key, "bucket": bucket}
    else:
        _BACKEND = "local"
        _CONF = {"dir": app.config["STORAGE_DIR"]}
        os.makedirs(_CONF["dir"], exist_ok=True)
    app.config["STORAGE_BACKEND"] = _BACKEND


def backend():
    return _BACKEND or "local"


def describe():
    if _BACKEND == "supabase":
        return f"Supabase Storage · 버킷 {_CONF['bucket']}"
    return f"로컬 파일 · {_CONF.get('dir', '')}"


# ─────────────────────────────────────────────────────────────
# 공통 API
# ─────────────────────────────────────────────────────────────

def save_bytes(name, data):
    if _BACKEND == "supabase":
        return _sb_upload(name, data)
    path = os.path.join(_CONF["dir"], name)
    with open(path, "wb") as f:
        f.write(data)
    return path


def read_bytes(name):
    if _BACKEND == "supabase":
        return _sb_download(name)
    path = os.path.join(_CONF["dir"], name)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def delete(name):
    if _BACKEND == "supabase":
        return _sb_delete(name)
    path = os.path.join(_CONF["dir"], name)
    if os.path.exists(path):
        os.remove(path)


def local_path(name):
    """PyMuPDF 가 읽을 수 있는 실제 경로를 준다.

    원격 저장소면 임시 파일로 내려받는다.
    서버리스에서 /tmp 는 요청 동안만 유효하다 — 그 안에서 처리하고 끝낸다.
    """
    if _BACKEND != "supabase":
        return os.path.join(_CONF["dir"], name), False
    data = _sb_download(name)
    if data is None:
        return None, False
    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return tmp, True


# ─────────────────────────────────────────────────────────────
# Supabase Storage (REST)
# ─────────────────────────────────────────────────────────────

def _sb_headers(content_type=None):
    h = {
        "Authorization": f"Bearer {_CONF['key']}",
        "apikey": _CONF["key"],
    }
    if content_type:
        h["Content-Type"] = content_type
    return h


def _sb_url(name):
    return f"{_CONF['url']}/storage/v1/object/{_CONF['bucket']}/{name}"


def _sb_upload(name, data):
    import urllib.request

    req = urllib.request.Request(
        _sb_url(name), data=data, method="POST",
        headers={**_sb_headers("application/pdf"), "x-upsert": "true"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        r.read()
    return name


def _sb_download(name):
    import urllib.error
    import urllib.request

    req = urllib.request.Request(_sb_url(name), headers=_sb_headers())
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError:
        return None


def _sb_delete(name):
    import urllib.error
    import urllib.request

    req = urllib.request.Request(_sb_url(name), method="DELETE", headers=_sb_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
    except urllib.error.HTTPError:
        pass
