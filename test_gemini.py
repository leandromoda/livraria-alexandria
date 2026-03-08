import requests
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent / "scripts" / ".env")

key = os.getenv("GEMINI_API_KEY", "")

if not key:
    print("[ERRO] GEMINI_API_KEY não encontrada no scripts/.env")
    exit(1)

print(f"[OK] Key carregada: ...{key[-6:]}")

model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")
print(f"[OK] Model: {model}")

url = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{model}:generateContent?key={key}"
)

payload = {
    "contents": [{"parts": [{"text": "diga ola"}]}],
    "generationConfig": {"maxOutputTokens": 20},
}

print("[...] Chamando Gemini API...")

r = requests.post(url, json=payload, timeout=30)

print(f"[STATUS] {r.status_code}")
print(r.text[:500])
