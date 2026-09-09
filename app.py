import os
import base64
import tempfile
from pathlib import Path

import requests
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="ETYC Image Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_IMAGE_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2.5-sunburst")

@app.get("/health")
def health():
    return {"ok": True, "model": OPENAI_IMAGE_MODEL}

@app.post("/edit")
async def edit_image(
    source_image: UploadFile = File(...),
    canon_image: UploadFile | None = File(None),
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
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY no configurada en el servidor.")

    source_bytes = await source_image.read()
    canon_bytes = await canon_image.read() if canon_image else None

    prompt = f"""
ETYC STUDIO — CONTROLLED IMAGE EDIT

USER REQUEST:
{instruction}

CHARACTER:
{character_id} — {character_name}

CANON SUMMARY:
{canon_summary}

LOCKED RULES:
{locked_rules}

LOCATION:
{location_name}

LOCATION CANON:
{location_canon}

SOURCE IMAGE USE:
{reference_types}

CANON LOCK:
{canon_lock}

INTERVENTION LEVEL:
{intervention}

INSTRUCTIONS:
Use the source image as the requested pose/composition reference.
When a canonical character reference image is provided, use it as the primary visual identity reference.
Preserve the canonical identity, age, facial structure, hair, beard, proportions, and defining traits.
Do not invent unrequested accessories.
Do not introduce watercolor or painterly drift.
For correction mode, change only what is necessary and preserve the rest of the image.
Return a finished comic-production image, without captions, UI, labels, or watermarks.
""".strip()

    files = [
        ("image[]", ("source.jpg", source_bytes, "image/jpeg")),
    ]
    if canon_bytes:
        files.append(("image[]", ("canon.jpg", canon_bytes, "image/jpeg")))

    data = {
        "model": OPENAI_IMAGE_MODEL,
        "prompt": prompt,
        "quality": "high",
        "size": "auto",
        "output_format": "png",
    }

    response = requests.post(
        "https://api.openai.com/v1/images/edits",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        data=data,
        files=files,
        timeout=180,
    )

    if not response.ok:
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text
        )

    payload = response.json()
    try:
        image_b64 = payload["data"][0]["b64_json"]
    except Exception:
        raise HTTPException(status_code=502, detail=f"Respuesta inesperada de OpenAI: {payload}")

    return {
        "image_base64": image_b64,
        "model": OPENAI_IMAGE_MODEL,
    }
