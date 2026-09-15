"""Vercel 서버리스 진입점.

Vercel 은 api/ 아래 파일을 함수로 만든다. vercel.json 의 rewrite 로 모든 경로를 여기로 보낸다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from esyr import create_app  # noqa: E402

app = create_app()
