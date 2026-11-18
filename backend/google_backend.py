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
# "Automatico" usa Google solo se attivato (variabile GCP_AUTO=1): la prima prova reale non ha finito in tempo.
AUTO = os.environ.get("MYSOGNI_GCP_AUTO", "") == "1"
# Limite del task Cloud Run (--task-timeout in gcp-deploy.yml di mysogni-gpu): va tenuto uguale.
TASK_TIMEOUT_S = 1800
# All'avvio si prenota il caso peggiore (il lavoro può durare fino al limite), corretto a lavoro concluso.
# Un lavoro mai più seguito dalla pagina resta prenotato per intero: la stima sbaglia per eccesso, mai per difetto.
RESERVE_S = TASK_TIMEOUT_S
LOOKUP_GRACE_S = 180  # dopo un invio dall'esito incerto: tempo massimo per trovare l'esecuzione


class Rejected(Exception):
    """Google ha risposto rifiutando il lavoro: è sicuro ripiegare su Modal."""


class Uncertain(Exception):
    """Invio dall'esito incerto (timeout, rete): NON ripiegare, il lavoro potrebbe essere partito."""
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
        """Spesa del mese: lavori conclusi più prenotazioni dei lavori in corso."""
        month = self._month()
        seconds = self.store.get(f"usage:{month}", 0.0) + self.store.get(f"reserved:{month}", 0.0)
        return round(seconds * RATE_USD_H / 3600, 2)

    def has_budget(self) -> bool:
        """C'è posto per un altro lavoro nel caso peggiore (durata pari al limite del task)?"""
        return self.spent_usd() + RESERVE_S * RATE_USD_H / 3600 <= BUDGET_USD

    def _reserve(self, job_id: str):
        month = self._month()
        self.store[f"reservation:{job_id}"] = {"month": month, "seconds": RESERVE_S}
        self.store[f"reserved:{month}"] = self.store.get(f"reserved:{month}", 0.0) + RESERVE_S

    def _release(self, job_id: str):
        reservation = self.store.pop(f"reservation:{job_id}", None)
        if reservation:
            key = f"reserved:{reservation['month']}"
            self.store[key] = max(0.0, self.store.get(key, 0.0) - reservation["seconds"])

    def _record(self, job_id: str, seconds: float):
        flag = f"billed:{job_id}"
        if self.store.get(flag):
            return
        self.store[flag] = True
        self._release(job_id)
        key = f"usage:{self._month()}"
        self.store[key] = self.store.get(key, 0.0) + max(seconds, 0.0)

    # --- lavori ---
    def start(self, config: dict) -> str:
        """Lancia il lavoro. Solleva Rejected (risposta di rifiuto) o Uncertain (esito ignoto: non ripiegare)."""
        import requests

        job_id = "g-" + uuid.uuid4().hex
        url = f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}/jobs/{JOB}:run"
        body = {"overrides": {"containerOverrides": [{"env": [
            {"name": "JOB_ID", "value": job_id},
            {"name": "CONFIG", "value": json.dumps(config)},
        ]}]}}
        try:
            token = self._token()
        except Exception as exc:  # credenziali: nessun lavoro può essere partito
            raise Rejected(f"Autenticazione Google non riuscita: {type(exc).__name__}")
        try:
            response = requests.post(url, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=60)
        except requests.RequestException:
            # Il lavoro potrebbe essere stato accettato: lo registriamo e lo cerchiamo, senza ripiegare.
            self.store[f"exec:{job_id}"] = {"execution": None, "started": time.time(), "uncertain": True}
            self._reserve(job_id)
            raise Uncertain(job_id)
        if not response.ok:
            message = ""
            try:
                message = response.json().get("error", {}).get("message", "")
            except Exception:
                pass
            raise Rejected(f"Google Cloud ha rifiutato il lavoro (HTTP {response.status_code}): {message[:300]}")
        execution = (response.json().get("metadata") or {}).get("name")
        self.store[f"exec:{job_id}"] = {"execution": execution, "started": time.time()}
        self._reserve(job_id)
        return job_id

    def _find_execution(self, job_id: str) -> str | None:
        """Cerca tra le esecuzioni recenti quella con JOB_ID uguale (dopo un invio dall'esito incerto)."""
        url = f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}/jobs/{JOB}/executions?pageSize=20"
        response = self._get(url)
        if not response.ok:
            return None
        for execution in response.json().get("executions", []):
            for container in (execution.get("template") or {}).get("containers", []):
                for env in container.get("env", []):
                    if env.get("name") == "JOB_ID" and env.get("value") == job_id:
                        return execution.get("name")
        return None

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
        if not info.get("execution"):
            found = self._find_execution(job_id)
            if found:
                info = {**info, "execution": found, "uncertain": False}
                self.store[f"exec:{job_id}"] = info
            elif time.time() - info.get("started", 0) > LOOKUP_GRACE_S:
                self._release(job_id)
                self.store[f"billed:{job_id}"] = True
                return {"status": "error", "backend": "google",
                        "error": "L'invio a Google non è andato a buon fine: nessuna esecuzione creata. Puoi riprovare."}
            else:
                return {"status": "running", "backend": "google"}
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
