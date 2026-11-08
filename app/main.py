from fastapi import FastAPI, UploadFile, File, Header, HTTPException, Request
from pydantic import BaseModel
from datetime import datetime, timezone
from collections import Counter
from typing import Optional
import os
import time
import uuid
import logging
import json
import hmac
import hashlib
import base64

app = FastAPI(title="MCHLERN BINARY ENGINE", version="0.2.0")
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mchlern")

# API_TOKEN is a server-side signing secret. Never put it in the Lua client.
API_TOKEN = os.getenv("API_TOKEN", "")
ACTIVATION_CODES = {
    item.strip()
    for item in os.getenv("MCHLERN_ACTIVATION_CODES", "").split(",")
    if item.strip()
}
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "40"))
MAX_INSTANCES = int(os.getenv("MAX_INSTANCES", "100000"))
JOB_TTL = int(os.getenv("JOB_TTL_SECONDS", "1800"))
SESSION_TTL = int(os.getenv("SESSION_TTL_SECONDS", "43200"))

JOBS = {}
ACTIVATION_ATTEMPTS = {}
MAX_ACTIVATION_ATTEMPTS_PER_MINUTE = 12


class ActivationRequest(BaseModel):
    code: str


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def issue_session() -> str:
    if not API_TOKEN:
        raise HTTPException(503, "API_TOKEN belum dipasang di Railway.")
    now = int(time.time())
    payload = json.dumps(
        {"sub": "mchlern-user", "iat": now, "exp": now + SESSION_TTL},
        separators=(",", ":")
    ).encode("utf-8")
    encoded = b64url(payload)
    signature = hmac.new(
        API_TOKEN.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).digest()
    return encoded + "." + b64url(signature)


def verify_session(authorization: Optional[str]):
    if not API_TOKEN:
        raise HTTPException(503, "Server authentication is not configured.")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Session token required.")
    token = authorization[7:].strip()
    try:
        encoded, supplied_sig = token.split(".", 1)
        expected_sig = b64url(hmac.new(
            API_TOKEN.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
        ).digest())
        if not hmac.compare_digest(supplied_sig, expected_sig):
            raise ValueError("Bad signature")
        payload_raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(payload_raw.decode("utf-8"))
        if int(payload.get("exp", 0)) <= int(time.time()):
            raise HTTPException(401, "Session expired. Activate again.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Invalid session token.")
    return payload


def cleanup():
    now = time.time()
    for job_id in list(JOBS):
        if now - JOBS[job_id]["created"] > JOB_TTL:
            del JOBS[job_id]


def parse_binary(data, file_type):
    if not data.startswith(b"<roblox!"):
        raise ValueError("Invalid Roblox binary signature.")
    try:
        from mchlern_parser import parse_bytes
    except ImportError:
        raise RuntimeError("RBXM/RBXL decoder belum diintegrasikan.")

    result = parse_bytes(data, file_type)
    if not isinstance(result, dict) or not isinstance(result.get("tree"), list):
        raise ValueError("Invalid parser response.")

    count = [0]
    class_counts = Counter()
    scripts = []

    def walk(nodes, parent=""):
        for node in nodes:
            if not isinstance(node, dict):
                raise ValueError("Invalid instance node.")
            count[0] += 1
            if count[0] > MAX_INSTANCES:
                raise ValueError("Instance limit exceeded.")
            class_name = str(node.get("className", "Unknown"))
            name = str(node.get("name", class_name))
            path = f"{parent}/{name}" if parent else name
            node["path"] = path
            class_counts[class_name] += 1
            if class_name in ("Script", "LocalScript", "ModuleScript"):
                scripts.append({
                    "name": name,
                    "className": class_name,
                    "path": path,
                    "sourceAvailable": isinstance(node.get("scriptSource"), str)
                })
            children = node.get("children", [])
            if not isinstance(children, list):
                raise ValueError("Invalid children.")
            walk(children, path)

    walk(result["tree"])
    return {
        "fileType": file_type,
        "instanceCount": count[0],
        "scriptCount": len(scripts),
        "classCounts": dict(class_counts),
        "scripts": scripts,
        "metadata": result.get("metadata", {}),
        "tree": result["tree"]
    }


@app.get("/")
def home():
    return {
        "name": "MCHLERN BINARY ENGINE",
        "status": "online",
        "version": "0.2.0",
        "authentication": "activation-code/session",
        "parser": "adapter-required"
    }


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "MCHLERN BINARY ENGINE",
        "time": datetime.now(timezone.utc).isoformat()
    }


@app.post("/api/auth/activate")
async def activate(payload: ActivationRequest, request: Request):
    if not API_TOKEN:
        raise HTTPException(503, "API_TOKEN belum dipasang di Railway.")
    if not ACTIVATION_CODES:
        raise HTTPException(503, "MCHLERN_ACTIVATION_CODES belum dipasang di Railway.")

    ip = request.client.host if request.client else "unknown"
    now = time.time()
    attempts = [t for t in ACTIVATION_ATTEMPTS.get(ip, []) if now - t < 60]
    if len(attempts) >= MAX_ACTIVATION_ATTEMPTS_PER_MINUTE:
        raise HTTPException(429, "Too many activation attempts. Try again later.")
    attempts.append(now)
    ACTIVATION_ATTEMPTS[ip] = attempts

    code = payload.code.strip()
    if not any(hmac.compare_digest(code, valid) for valid in ACTIVATION_CODES):
        raise HTTPException(401, "Invalid activation code.")

    return {
        "ok": True,
        "token_type": "bearer",
        "access_token": issue_session(),
        "expires_in": SESSION_TTL
    }


async def process_upload(file_type, file, authorization):
    verify_session(authorization)
    cleanup()
    filename = file.filename or ""
    if not filename.lower().endswith("." + file_type):
        raise HTTPException(415, "Wrong file extension.")
    data = await file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if not data:
        raise HTTPException(400, "Empty file.")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, "File too large.")
    try:
        manifest = parse_binary(data, file_type)
    except RuntimeError as error:
        raise HTTPException(501, str(error))
    except ValueError as error:
        raise HTTPException(422, str(error))
    except Exception:
        log.exception("Parser failed")
        raise HTTPException(422, "Unable to parse file.")

    job_id = uuid.uuid4().hex
    JOBS[job_id] = {
        "created": time.time(), "filename": filename,
        "file_type": file_type, "file_size": len(data),
        "manifest": manifest
    }
    return {
        "ok": True, "job_id": job_id, "status": "completed",
        "filename": filename,
        "summary": {
            "instanceCount": manifest["instanceCount"],
            "scriptCount": manifest["scriptCount"],
            "classCounts": manifest["classCounts"]
        },
        "manifest_url": f"/api/jobs/{job_id}/manifest"
    }


@app.post("/api/upload/rbxm")
async def upload_rbxm(
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None)
):
    return await process_upload("rbxm", file, authorization)


@app.post("/api/upload/rbxl")
async def upload_rbxl(
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None)
):
    return await process_upload("rbxl", file, authorization)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, authorization: Optional[str] = Header(None)):
    verify_session(authorization)
    cleanup()
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    return {
        "job_id": job_id, "status": "completed",
        "filename": job["filename"], "file_type": job["file_type"],
        "file_size": job["file_size"]
    }


@app.get("/api/jobs/{job_id}/manifest")
def get_manifest(job_id: str, authorization: Optional[str] = Header(None)):
    verify_session(authorization)
    cleanup()
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    return {
        "ok": True, "job_id": job_id,
        "filename": job["filename"], "manifest": job["manifest"]
    }
