import base64
import io
import os
from typing import Optional

import requests
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

app = FastAPI(title="ETYC Free Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_GATEWAY_ID = os.getenv("CLOUDFLARE_GATEWAY_ID", "default")
CLOUDFLARE_MODEL = os.getenv(
    "CLOUDFLARE_MODEL",
    "@cf/black-forest-labs/flux-2-klein-4b"
)

def resize_for_flux(raw: bytes, max_dim: int = 500) -> bytes:
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    image.thumbnail((max_dim, max_dim))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90)
    return out.getvalue()

@app.get("/health")
def health():
    account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    token = os.getenv("CLOUDFLARE_API_TOKEN", "")

    cloudflare_keys = sorted([
        key for key in os.environ.keys()
        if key.upper().startswith("CLOUDFLARE")
    ])

    return {
        "ok": bool(account.strip()) and bool(token.strip()),
        "account_present": bool(account.strip()),
        "account_length": len(account.strip()),
        "token_present": bool(token.strip()),
        "token_length": len(token.strip()),
        "cloudflare_env_keys": cloudflare_keys,
        "expected_keys": [
            "CLOUDFLARE_ACCOUNT_ID",
            "CLOUDFLARE_API_TOKEN",
            "CLOUDFLARE_GATEWAY_ID",
            "CLOUDFLARE_MODEL"
        ]
    }
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
    intervention: str = Form("Corrección"),
    instruction: str = Form(""),
):
    if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="Faltan CLOUDFLARE_ACCOUNT_ID o CLOUDFLARE_API_TOKEN."
        )

    source_bytes = resize_for_flux(await source_image.read())

    canon_bytes = None
    if canon_image is not None:
        canon_bytes = resize_for_flux(await canon_image.read())

    prompt = f"""
ETYC STUDIO FREE EDITION

Character: {character_id} — {character_name}

Canon:
{canon_summary}

Locked rules:
{locked_rules}

Location:
{location_name}

Location canon:
{location_canon}

Reference intent:
{reference_types}

Canon Lock:
{canon_lock}

Intervention:
{intervention}

User instruction:
{instruction}

Image 0 is the canonical character reference when present.
Image 1 is the source photo used for pose, framing or composition.

Preserve the canonical identity and defining traits.
Use the source image mainly for pose and composition.
Do not introduce watercolor or painterly drift.
Do not add unrequested accessories.
Do not add text, captions, UI or watermarks.
""".strip()

    url = (
        f"https://api.cloudflare.com/client/v4/accounts/"
        f"{CLOUDFLARE_ACCOUNT_ID}/ai/run/{CLOUDFLARE_MODEL}"
    )

    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "cf-aig-gateway-id": CLOUDFLARE_GATEWAY_ID,
    }

    files = [
        ("input_image_1", ("source.jpg", source_bytes, "image/jpeg")),
        ("prompt", (None, prompt)),
        ("width", (None, "1024")),
        ("height", (None, "1024")),
        ("guidance", (None, "5.5")),
    ]

    if canon_bytes is not None:
        files.insert(
            0,
            ("input_image_0", ("canon.jpg", canon_bytes, "image/jpeg"))
        )

    response = requests.post(
        url,
        headers=headers,
        files=files,
        timeout=240
    )

    if not response.ok:
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text
        )

    payload = response.json()

    image_b64 = None
    if isinstance(payload, dict):
        image_b64 = payload.get("result", {}).get("image") or payload.get("image")

    if not image_b64:
        raise HTTPException(
            status_code=502,
            detail=f"Respuesta inesperada de Cloudflare: {payload}"
        )

    return {
        "image_base64": image_b64,
        "provider": "Cloudflare Workers AI",
        "model": CLOUDFLARE_MODEL,
    }
