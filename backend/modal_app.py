"""MySogni Web: router web su Modal.

Modelli:
- "test": video di prova generato con ffmpeg su CPU, gratuito; serve a collaudare il percorso.
- "h3-prism": MiniMax H3 PRISM su GPU, tramite l'app privata `mysogni-gpu` (repository Vale717171/mysogni-gpu).
  Disponibile solo se il deploy imposta MYSOGNI_GPU_ENABLED=1: è l'interruttore che autorizza la spesa GPU.

Pubblicazione: `modal deploy backend/modal_app.py` (lo fa GitHub Actions a ogni push su main).
"""

import os
import time
from pathlib import Path

import modal

APP_NAME = "mysogni-web"
GPU_APP_NAME = "mysogni-gpu"
OUTPUT_DIR = "/outputs"
RETENTION_DAYS = 7
ALLOWED_DURATIONS = {5, 10, 15}
PRISM_RESOLUTIONS = {"1344x768": (1344, 768), "896x512": (896, 512)}
ULTRAFAST_RESOLUTIONS = {"896x512": (896, 512), "672x384": (672, 384)}
M3_CHOICES = [0.6, 1.0, 0.0]  # il primo è il predefinito
ALLOWED_ORIGINS = [
    "https://vale717171.github.io",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# Letta in locale al deploy e copiata nell'immagine, così vale anche dentro i container.
GPU_ENABLED = os.environ.get("MYSOGNI_GPU_ENABLED", "0") == "1"
# UltraFast richiede anche i pesi nel Volume (workflow "Scarica i pesi UltraFast" in mysogni-gpu): interruttore separato.
ULTRAFAST_ENABLED = GPU_ENABLED and os.environ.get("MYSOGNI_ULTRAFAST_ENABLED", "0") == "1"

# Screenwriter: modello linguistico via Cheaper Inference (API compatibile OpenAI), sempre con zero data retention.
LLM_BASE_URL = os.environ.get("MYSOGNI_LLM_BASE_URL") or "https://api.cheaperinference.com/v1"
LLM_MODEL = os.environ.get("MYSOGNI_LLM_MODEL") or "deepseek-v4-flash-0731"

app = modal.App(APP_NAME)

outputs = modal.Volume.from_name("mysogni-web-outputs", create_if_missing=True)
# Configurazione privata (system prompt dello screenwriter), scritta dal workflow del repository privato mysogni-gpu.
private_config = modal.Volume.from_name("mysogni-private-config", create_if_missing=True)

web_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("fastapi[standard]")
    .env(
        {
            "MYSOGNI_GPU_ENABLED": "1" if GPU_ENABLED else "0",
            "MYSOGNI_ULTRAFAST_ENABLED": "1" if ULTRAFAST_ENABLED else "0",
            "MYSOGNI_LLM_BASE_URL": LLM_BASE_URL,
            "MYSOGNI_LLM_MODEL": LLM_MODEL,
        }
    )
    .add_local_file(Path(__file__).parent / "screenwriter.py", "/root/screenwriter.py")
)
fake_worker_image = modal.Image.debian_slim(python_version="3.12").apt_install("ffmpeg")


def available_models() -> list[dict]:
    models = [
        {
            "id": "test",
            "label": "Video di prova (gratuito)",
            "note": "Barre colorate generate su CPU: serve a collaudare il percorso.",
            "resolutions": [],
        }
    ]
    if GPU_ENABLED:
        models.insert(
            0,
            {
                "id": "h3-prism",
                "label": "H3 PRISM (GPU)",
                "note": "Stima dal pilota, a freddo, 1344×768: 5 s in circa 3 min (0,19 $), 15 s in circa 12 min (0,75 $).",
                "resolutions": list(PRISM_RESOLUTIONS),
            },
        )
    if ULTRAFAST_ENABLED:
        models.insert(
            0,
            {
                "id": "h3-ultrafast-int8",
                "label": "H3 UltraFast INT8 + M3 (GPU)",
                "note": "6 step con Turbo LoRA, LoRA M3 di default a 0,6. Mai misurato su Modal: su Colab il profilo NVFP4 a 672×384 ha fatto 5 s in 16 s di workflow, più l'avvio a freddo.",
                "resolutions": list(ULTRAFAST_RESOLUTIONS),
                "m3": M3_CHOICES,
            },
        )
    return models


@app.function(image=fake_worker_image, volumes={OUTPUT_DIR: outputs}, timeout=600)
def generate(prompt: str, duration: int, model: str, seed: int | None) -> dict:
    """Video di prova: nessuna GPU."""
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
        "model": "test",
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
    volumes={OUTPUT_DIR: outputs, "/config": private_config},
    secrets=[modal.Secret.from_name("mysogni-web-auth"), modal.Secret.from_name("mysogni-web-llm")],
    timeout=120,
)
@modal.concurrent(max_inputs=20)
@modal.asgi_app(label="mysogni-web-api")
def api():
    import hmac
    import random

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
        prompt: str = Field(min_length=1, max_length=8000)
        duration: int = 5
        model: str = "test"
        backend: str = "auto"
        resolution: str | None = None
        m3_strength: float | None = None
        seed: int | None = None

    class ScreenwriterRequest(BaseModel):
        idea: str = Field(min_length=1, max_length=4000)
        duration: int = 5

    llm_key = os.environ.get("LLM_API_KEY", "").strip()
    if llm_key == "unset":  # segnaposto scritto dal workflow quando manca il secret GitHub
        llm_key = ""

    @web.get("/health")
    def health():
        return {
            "ok": True,
            "gpu_enabled": GPU_ENABLED,
            "ultrafast_enabled": ULTRAFAST_ENABLED,
            "models": available_models(),
            "screenwriter": {"enabled": bool(llm_key), "model": LLM_MODEL, "prompt": _prompt_source()},
        }

    def _reload_config() -> None:
        try:
            private_config.reload()
        except Exception:
            pass  # fuori da Modal (prove locali) o Volume non ancora popolato: si usa il prompt di riserva

    def _prompt_source() -> str:
        from screenwriter import system_prompt

        _reload_config()
        return system_prompt()[1]

    @web.post("/screenwriter")
    async def screenwriter(req: ScreenwriterRequest):
        import httpx
        from screenwriter import build_messages, clean_output

        try:
            await private_config.reload.aio()
        except Exception:
            pass
        messages, prompt_source = build_messages(req.idea, req.duration)

        if req.duration not in ALLOWED_DURATIONS:
            raise HTTPException(400, f"Durata non ammessa: {req.duration}")
        if not llm_key:
            raise HTTPException(503, "Screenwriter non configurato: manca la chiave di Cheaper Inference")
        body = {
            "model": LLM_MODEL,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 4000,
            "zdr": True,  # zero data retention: solo fornitori che non conservano richieste e risposte
        }
        try:
            async with httpx.AsyncClient(timeout=100) as client:
                r = await client.post(
                    f"{LLM_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {llm_key}"},
                    json=body,
                )
        except httpx.HTTPError:
            raise HTTPException(502, "Cheaper Inference non raggiungibile o troppo lento")
        if r.status_code != 200:
            code, message = "", ""
            try:
                error = r.json().get("error") or {}
                code = str(error.get("code") or error.get("type") or "")
                message = str(error.get("message") or "")
            except Exception:
                pass
            if code == "zdr_capacity_unavailable":
                raise HTTPException(
                    503, f"Nessun fornitore con zero data retention disponibile ora per {LLM_MODEL}: riprova più tardi"
                )
            raise HTTPException(502, f"Cheaper Inference ha risposto {r.status_code} {code}: {message[:200]}".strip())
        try:
            choice = r.json()["choices"][0]
            prompt = clean_output(choice["message"].get("content") or "", req.duration, choice.get("finish_reason"))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise HTTPException(502, f"Risposta del modello non utilizzabile: {exc}")
        return {"prompt": prompt, "model": LLM_MODEL, "duration": req.duration, "prompt_source": prompt_source}

    @web.post("/jobs")
    def create_job(req: JobRequest):
        model_ids = {m["id"] for m in available_models()}
        if req.model not in model_ids:
            raise HTTPException(400, f"Modello non disponibile: {req.model}")
        if req.duration not in ALLOWED_DURATIONS:
            raise HTTPException(400, f"Durata non ammessa: {req.duration}")
        if req.backend not in {"auto", "modal"}:
            raise HTTPException(400, "Backend non disponibile (Cloud Run arriva con M2)")
        if req.seed is not None and not 0 <= req.seed < 2**63:
            raise HTTPException(400, "Seed non valido")
        _cleanup_old_outputs()

        if req.model == "test":
            call = generate.spawn(req.prompt, req.duration, req.model, req.seed)
            return {"job_id": call.object_id, "backend": "modal", "model": "test"}

        if req.model == "h3-ultrafast-int8":
            resolution = req.resolution or "896x512"
            if resolution not in ULTRAFAST_RESOLUTIONS:
                raise HTTPException(400, f"Risoluzione non ammessa: {resolution}")
            m3 = M3_CHOICES[0] if req.m3_strength is None else req.m3_strength
            if not 0 <= m3 <= 2:
                raise HTTPException(400, "Intensità M3: da 0 a 2")
            if req.seed is not None and req.seed >= 2**32:
                raise HTTPException(400, "Seed UltraFast: da 0 a 2^32-1")
            width, height = ULTRAFAST_RESOLUTIONS[resolution]
            seed = req.seed if req.seed is not None else random.randrange(2**32)
            worker = modal.Cls.from_name(GPU_APP_NAME, "UltraFast")
            call = worker().generate.spawn(
                {"prompt": req.prompt, "duration": req.duration, "width": width, "height": height, "seed": seed,
                 "m3_strength": m3}
            )
            return {"job_id": call.object_id, "backend": "modal", "model": req.model, "seed": seed}

        resolution = req.resolution or "1344x768"
        if resolution not in PRISM_RESOLUTIONS:
            raise HTTPException(400, f"Risoluzione non ammessa: {resolution}")
        width, height = PRISM_RESOLUTIONS[resolution]
        seed = req.seed if req.seed is not None else random.randrange(2**31)
        generator = modal.Cls.from_name(GPU_APP_NAME, "Generator")
        call = generator().generate.spawn(
            {"prompt": req.prompt, "duration": req.duration, "width": width, "height": height, "seed": seed}
        )
        return {"job_id": call.object_id, "backend": "modal", "model": req.model, "seed": seed}

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
            return {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
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
