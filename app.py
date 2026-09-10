import io
import os
from typing import Optional

import requests
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

app = FastAPI(title="ETYC Free Backend Diagnostic")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

def env_status():
    account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    token = os.getenv("CLOUDFLARE_API_TOKEN", "")
    gateway = os.getenv("CLOUDFLARE_GATEWAY_ID", "default")
    model = os.getenv("CLOUDFLARE_MODEL", "@cf/black-forest-labs/flux-2-klein-4b")
    return {
        "account_present": bool(account.strip()),
        "account_length": len(account.strip()),
        "token_present": bool(token.strip()),
        "token_length": len(token.strip()),
        "gateway_id": gateway,
        "model": model,
    }

@app.on_event("startup")
def startup_debug():
    s = env_status()
    print("ETYC ENV STATUS:", s)

@app.get("/health")
def health():
    s = env_status()
    return {
        "ok": s["account_present"] and s["token_present"],
        "provider": "Cloudflare Workers AI",
        **s,
    }

def resize_for_flux(raw: bytes, max_dim: int = 500) -> bytes:
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    image.thumbnail((max_dim, max_dim))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90)
    return out.getvalue()

@app.post("/edit")
async def edit_image(
    source_image: UploadFile = File(...),
    canon_image: Optional[UploadFile] = File(None),
    character_id: str = Form(""),
    character_name: str = Form(""),
    canon_summary: str = Form(""),
    locked_rules: str = Form(""),
    location_name: str = Form(""),
    location_canon: str = Form(""),
    reference_types: str = Form(""),
    canon_lock: str = Form("true"),
    intervention: str = Form("CorrecciÃ³n"),
    instruction: str = Form(""),
):
    s = env_status()
    missing = []
    if not s["account_present"]:
        missing.append("CLOUDFLARE_ACCOUNT_ID")
    if not s["token_present"]:
        missing.append("CLOUDFLARE_API_TOKEN")

    if missing:
        raise HTTPException(status_code=500, detail={
            "message": "Faltan variables de entorno en Render.",
            "missing": missing,
            "account_present": s["account_present"],
            "token_present": s["token_present"],
        })

    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    api_token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    gateway_id = os.getenv("CLOUDFLARE_GATEWAY_ID", "default").strip()
    model = os.getenv("CLOUDFLARE_MODEL", "@cf/black-forest-labs/flux-2-klein-4b").strip()

    source_bytes = resize_for_flux(await source_image.read())
    canon_bytes = resize_for_flux(await canon_image.read()) if canon_image is not None else None

    prompt = f"""
ETYC STUDIO FREE EDITION

Character: {character_id} â {character_name}
Canon: {canon_summary}
Locked rules: {locked_rules}
Location: {location_name}
Location canon: {location_canon}
Reference intent: {reference_types}
Canon Lock: {canon_lock}
Intervention: {intervention}
User instruction: {instruction}

Image 0 is the canonical character reference when present.
Image 1 is the source photo used for pose, framing or composition.
Preserve canonical identity and defining traits.
Use the source image mainly for pose and composition.
Avoid watercolor or painterly drift.
Do not add unrequested accessories, text, captions, UI or watermarks.
""".strip()

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "cf-aig-gateway-id": gateway_id,
    }
    files = [
        ("input_image_1", ("source.jpg", source_bytes, "image/jpeg")),
        ("prompt", (None, prompt)),
        ("width", (None, "1024")),
        ("height", (None, "1024")),
        ("guidance", (None, "5.5")),
    ]
    if canon_bytes is not None:
        files.insert(0, ("input_image_0", ("canon.jpg", canon_bytes, "image/jpeg")))

    response = requests.post(url, headers=headers, files=files, timeout=240)
    if not response.ok:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    payload = response.json()
    image_b64 = payload.get("result", {}).get("image") if isinstance(payload, dict) else None
    if not image_b64 and isinstance(payload, dict):
        image_b64 = payload.get("image")

    if not image_b64:
        raise HTTPException(status_code=502, detail={
            "message": "Respuesta inesperada de Cloudflare.",
            "cloudflare_success": payload.get("success") if isinstance(payload, dict) else None,
            "cloudflare_errors": payload.get("errors") if isinstance(payload, dict) else None,
        })

    return {
        "image_base64": image_b64,
        "provider": "Cloudflare Workers AI",
        "model": model,
    }
