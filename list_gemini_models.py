import requests
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent / "scripts" / ".env")

key = os.getenv("GEMINI_API_KEY", "")

if not key:
    print("[ERRO] GEMINI_API_KEY não encontrada")
    exit(1)

url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"

r = requests.get(url, timeout=30)

print(f"[STATUS] {r.status_code}\n")

if r.status_code == 200:
    models = r.json().get("models", [])
    for m in models:
        name = m.get("name", "")
        supported = m.get("supportedGenerationMethods", [])
        if "generateContent" in supported:
            print(f"[OK] {name}")
else:
    print(r.text[:500])
