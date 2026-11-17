"""Backend Google Cloud: esegue il lavoro Cloud Run `mysogni-turbo-bf16` (repository privato mysogni-gpu).

Il lavoro scrive <job_id>.mp4 e <job_id>.json nel bucket <progetto>-results; il router li legge da qui.
La spesa del mese è stimata dalla durata delle esecuzioni (tariffa oraria configurabile) e serve a passare
a Modal quando si avvicina il budget dei crediti. È una stima: la cifra vera è nella fatturazione Google.
Né il prompt né la configurazione vengono scritti nei log.
"""

import base64
import json
import os
import time
import uuid
from datetime import datetime, timezone

PROJECT = os.environ.get("MYSOGNI_GCP_PROJECT", "")
REGION = os.environ.get("MYSOGNI_GCP_REGION") or "europe-west4"
JOB = os.environ.get("MYSOGNI_GCP_JOB") or "mysogni-turbo-bf16"
BUDGET_USD = float(os.environ.get("MYSOGNI_GCP_BUDGET_USD") or 8.5)
# RTX PRO 6000 senza ridondanza di zona + 20 vCPU + 80 GiB (minimi imposti), circa, in USD/ora.
RATE_USD_H = float(os.environ.get("MYSOGNI_GCP_RATE_USD_H") or 3.9)
MODELS = {"h3-turbo-bf16"}
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


def _key() -> dict | None:
    raw = os.environ.get("GCP_KEY_B64", "").strip()
    if not raw or raw == "unset":
        return None
    try:
        return json.loads(base64.b64decode(raw))
    except Exception:
        return None


def enabled() -> bool:
    return bool(PROJECT) and _key() is not None


class Google:
    def __init__(self, store):
        """store: dizionario persistente (modal.Dict) per esecuzioni e spesa mensile."""
        self.store = store
        self._credentials = None

    # --- autenticazione ---
    def _token(self) -> str:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        if self._credentials is None:
            self._credentials = service_account.Credentials.from_service_account_info(_key(), scopes=SCOPES)
        if not self._credentials.valid:
            self._credentials.refresh(Request())
        return self._credentials.token

    def _get(self, url: str, **kwargs):
        import requests

        return requests.get(url, headers={"Authorization": f"Bearer {self._token()}"}, timeout=60, **kwargs)

    # --- spesa ---
    @staticmethod
    def _month() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def spent_usd(self) -> float:
        return round(self.store.get(f"usage:{self._month()}", 0.0) * RATE_USD_H / 3600, 2)

    def has_budget(self) -> bool:
        return self.spent_usd() < BUDGET_USD

    def _record(self, job_id: str, seconds: float):
        flag = f"billed:{job_id}"
        if self.store.get(flag):
            return
        self.store[flag] = True
        key = f"usage:{self._month()}"
        self.store[key] = self.store.get(key, 0.0) + max(seconds, 0.0)

    # --- lavori ---
    def start(self, config: dict) -> str:
        import requests

        job_id = "g-" + uuid.uuid4().hex
        url = f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}/jobs/{JOB}:run"
        body = {"overrides": {"containerOverrides": [{"env": [
            {"name": "JOB_ID", "value": job_id},
            {"name": "CONFIG", "value": json.dumps(config)},
        ]}]}}
        response = requests.post(url, json=body, headers={"Authorization": f"Bearer {self._token()}"}, timeout=60)
        if not response.ok:
            message = ""
            try:
                message = response.json().get("error", {}).get("message", "")
            except Exception:
                pass
            raise RuntimeError(f"Google Cloud ha rifiutato il lavoro (HTTP {response.status_code}): {message[:300]}")
        execution = (response.json().get("metadata") or {}).get("name")
        self.store[f"exec:{job_id}"] = {"execution": execution, "started": time.time()}
        return job_id

    def _object(self, name: str):
        bucket = f"{PROJECT}-results"
        return self._get(f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{name}?alt=media")

    def _execution(self, job_id: str) -> dict:
        info = self.store.get(f"exec:{job_id}") or {}
        if not info.get("execution"):
            return {}
        response = self._get(f"https://run.googleapis.com/v2/{info['execution']}")
        return response.json() if response.ok else {}

    @staticmethod
    def _seconds(execution: dict, fallback_start: float | None) -> float:
        def parse(value):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() if value else None

        start = parse(execution.get("startTime")) or fallback_start or time.time()
        end = parse(execution.get("completionTime")) or time.time()
        return end - start

    def status(self, job_id: str) -> dict:
        info = self.store.get(f"exec:{job_id}")
        if info is None:
            return {"status": "expired"}
        response = self._object(f"{job_id}.json")
        if response.status_code == 200:
            result = response.json()
            self._record(job_id, self._seconds(self._execution(job_id), info.get("started")))
            return {**result, "backend": "google"}
        if response.status_code != 404:
            raise RuntimeError(f"Lettura del risultato da Google non riuscita (HTTP {response.status_code})")
        execution = self._execution(job_id)
        if execution.get("completionTime") and not execution.get("succeededCount"):
            self._record(job_id, self._seconds(execution, info.get("started")))
            return {"status": "error", "backend": "google",
                    "error": "Il lavoro Google si è fermato senza risultato: vedi i log di Cloud Run"}
        return {"status": "running", "backend": "google"}

    def video(self, job_id: str, target: str):
        response = self._object(f"{job_id}.mp4")
        if response.status_code != 200:
            return False
        with open(target, "wb") as stream:
            stream.write(response.content)
        return True
