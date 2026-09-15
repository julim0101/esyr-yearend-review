"""ESYR 실행 — 127.0.0.1 로만 접속을 허용한다."""
from esyr import create_app

app = create_app()

if __name__ == "__main__":
    print("ESYR · Etners Smart Year-end Review")
    print("  http://127.0.0.1:5000  (종료: Ctrl+C)")
    app.run(host="127.0.0.1", port=5000, debug=False)
