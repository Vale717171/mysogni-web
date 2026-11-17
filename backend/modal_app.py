"""MySogni Web: router web + worker su Modal.

Fase attuale: worker finto (MYSOGNI_FAKE_WORKER=1) che produce un video di prova
con ffmpeg su CPU, per collaudare tutto il percorso senza usare GPU.

Pubblicazione: `modal deploy backend/modal_app.py` (lo fa GitHub Actions a ogni push su main).
"""

import os
import time
from pathlib import Path

import modal

APP_NAME = "mysogni-web"
OUTPUT_DIR = "/outputs"
RETENTION_DAYS = 7
ALLOWED_DURATIONS = {5, 10, 15}
ALLOWED_MODELS = {"h3-ultrafast"}
ALLOWED_ORIGINS = [
    "https://vale717171.github.io",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# Letta al momento del deploy: "1" = worker finto su CPU, "0" = worker GPU reale (non ancora presente).
FAKE_WORKER = os.environ.get("MYSOGNI_FAKE_WORKER", "1") == "1"

app = modal.App(APP_NAME)

outputs = modal.Volume.from_name("mysogni-web-outputs", create_if_missing=True)

web_image = modal.Image.debian_slim(python_version="3.12").pip_install("fastapi[standard]")
fake_worker_image = modal.Image.debian_slim(python_version="3.12").apt_install("ffmpeg")


@app.function(image=fake_worker_image, volumes={OUTPUT_DIR: outputs}, timeout=600)
def generate(prompt: str, duration: int, model: str, seed: int | None) -> dict:
    """Genera il video. Per ora: video di prova, nessuna GPU."""
    import subprocess

    started = time.time()
    call_id = modal.current_function_call_id()
    out_path = Path(OUTPUT_DIR) / f"{call_id}.mp4"

    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc2=duration={duration}:size=384x384:rate=24",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast",
            str(out_path),
        ],
        check=True,
    )
    outputs.commit()

    return {
        "fake": True,
        "model": model,
        "duration": duration,
        "seed": seed,
        "bytes": out_path.stat().st_size,
        "timings": {"total_s": round(time.time() - started, 2)},
    }


def _cleanup_old_outputs() -> None:
    """Cancella i video più vecchi di RETENTION_DAYS giorni."""
    cutoff = time.time() - RETENTION_DAYS * 86400
    removed = False
    for path in Path(OUTPUT_DIR).glob("*.mp4"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed = True
        except FileNotFoundError:
            pass
    if removed:
        outputs.commit()


# Autenticazione: token bearer custodito nel secret Modal "mysogni-web-auth" (chiave API_TOKEN).
# Il proxy token di Modal non si usa qui perché blocca la richiesta preliminare CORS del browser.
@app.function(
    image=web_image,
    volumes={OUTPUT_DIR: outputs},
    secrets=[modal.Secret.from_name("mysogni-web-auth")],
    timeout=120,
)
@modal.concurrent(max_inputs=20)
@modal.asgi_app(label="mysogni-web-api")
def api():
    import hmac

    from fastapi import Depends, FastAPI, Header, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse
    from pydantic import BaseModel, Field

    expected = os.environ.get("API_TOKEN", "")

    def check_token(authorization: str = Header(default="")):
        supplied = authorization.removeprefix("Bearer ").strip()
        if not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
            raise HTTPException(401, "Token mancante o non valido")

    web = FastAPI(title="MySogni Web", docs_url=None, redoc_url=None, dependencies=[Depends(check_token)])
    web.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )

    class JobRequest(BaseModel):
        prompt: str = Field(min_length=1, max_length=4000)
        duration: int = 5
        model: str = "h3-ultrafast"
        backend: str = "auto"
        seed: int | None = None

    @web.get("/health")
    def health():
        return {"ok": True, "fake_worker": FAKE_WORKER}

    @web.post("/jobs")
    def create_job(req: JobRequest):
        if req.duration not in ALLOWED_DURATIONS:
            raise HTTPException(400, f"Durata non ammessa: {req.duration}")
        if req.model not in ALLOWED_MODELS:
            raise HTTPException(400, f"Modello non disponibile: {req.model}")
        if req.backend not in {"auto", "modal"}:
            raise HTTPException(400, "Backend non disponibile (Cloud Run arriva con M2)")
        _cleanup_old_outputs()
        call = generate.spawn(req.prompt, req.duration, req.model, req.seed)
        return {"job_id": call.object_id, "backend": "modal", "fake": FAKE_WORKER}

    @web.get("/jobs/{job_id}")
    def job_status(job_id: str):
        try:
            call = modal.FunctionCall.from_id(job_id)
        except Exception:
            raise HTTPException(404, "Job non trovato")
        try:
            result = call.get(timeout=0)
        except (TimeoutError, modal.exception.TimeoutError):
            return {"status": "running"}
        except modal.exception.OutputExpiredError:
            return {"status": "expired"}
        except Exception as exc:  # errore nel worker
            return {"status": "error", "error": type(exc).__name__}
        return {"status": "done", **result}

    @web.get("/jobs/{job_id}/video")
    def job_video(job_id: str):
        if not job_id.replace("-", "").isalnum():
            raise HTTPException(400, "ID non valido")
        outputs.reload()
        path = Path(OUTPUT_DIR) / f"{job_id}.mp4"
        if not path.exists():
            raise HTTPException(404, "Video non disponibile")
        return FileResponse(path, media_type="video/mp4", filename=f"mysogni-{job_id}.mp4")

    return web
