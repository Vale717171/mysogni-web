# MySogni Web: istruzioni per gli agenti

Pagina web (GitHub Pages) per generare video con MiniMax H3 su GPU remote. Il piano completo è nel documento "MySogni Web – struttura e primo traguardo"; qui ci sono le regole operative.

## Regole

- Nessuna generazione su GPU, nessun cambio di piano o limite di spesa su Modal o Google Cloud senza il consenso esplicito di Valentino. Il worker finto (`MYSOGNI_FAKE_WORKER=1`, predefinito) non usa GPU e si può collaudare liberamente.
- Nessun segreto nel repository: il repository è pubblico. Token e chiavi stanno solo nei secret di GitHub o di Modal.
- Prompt e video non vanno mai committati né scritti nei log di GitHub Actions.
- Lavora su un ramo separato e apri una pull request; `main` pubblica in automatico pagina e backend.
- Distingui sempre tra prova simulata (worker finto), prova reale e ipotesi.

## Mappa

- `docs/`: la pagina statica pubblicata da `.github/workflows/pages.yml`.
- `backend/modal_app.py`: router web (CPU) e worker, pubblicati da `.github/workflows/deploy-modal.yml`.
- `backend/worker/`: ricetta H3 (dal traguardo M1 reale in poi), portata da MySogni (`Vale717171/MySogni`, script UltraFast di Colab).

## Contratto dell'API

- `POST /jobs` con `{prompt, duration, model, backend, seed?}` restituisce `{job_id, backend}`.
- `GET /jobs/{job_id}` restituisce `{status: running|done|error, ...}` e, a job concluso, i tempi misurati.
- `GET /jobs/{job_id}/video` restituisce l'MP4.

Ogni richiesta porta `Authorization: Bearer <token>`. Il token sta nel secret GitHub `MYSOGNI_API_TOKEN`, che il workflow copia nel secret Modal `mysogni-web-auth` (chiave `API_TOKEN`). Il proxy token di Modal non si usa perché blocca la richiesta preliminare CORS del browser (verificato il 17/11/2026).
