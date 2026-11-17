# MySogni Web: istruzioni per gli agenti

Pagina web (GitHub Pages) per generare video con MiniMax H3 su GPU remote. Il piano completo è nel documento "MySogni Web – struttura e primo traguardo"; qui ci sono le regole operative.

## Regole

- Nessuna generazione su GPU, nessun cambio di piano o limite di spesa su Modal o Google Cloud senza il consenso esplicito di Valentino. Il modello `test` non usa GPU e si può collaudare liberamente. Il modello `h3-prism` esiste solo se la variabile di repository `MYSOGNI_GPU_ENABLED` vale `1`: non attivarla e non lanciare lavori `h3-prism` senza consenso.
- Nessun segreto nel repository: il repository è pubblico. Token e chiavi stanno solo nei secret di GitHub o di Modal.
- Prompt e video non vanno mai committati né scritti nei log di GitHub Actions.
- Lavora su un ramo separato e apri una pull request; `main` pubblica in automatico pagina e backend.
- Distingui sempre tra prova simulata (worker finto), prova reale e ipotesi.

## Mappa

- `docs/`: la pagina statica pubblicata da `.github/workflows/pages.yml`.
- `backend/modal_app.py`: router web (CPU) e worker di prova, pubblicati da `.github/workflows/deploy-modal.yml`.
- Worker GPU: repository privato `Vale717171/mysogni-gpu`, app Modal `mysogni-gpu`, classe `Generator`. Il router lo chiama per nome con `modal.Cls.from_name`; il codice PRISM non va copiato qui, perché questo repository è pubblico.
- `backend/worker/`: segnaposto per il futuro modello UltraFast (script di Colab di MySogni).

## Contratto dell'API

- `GET /health` restituisce `{ok, gpu_enabled, models}`; la pagina costruisce da qui l'elenco dei modelli e delle risoluzioni.
- `POST /jobs` con `{prompt, duration, model: test|h3-prism, backend, resolution?: 1344x768|896x512, seed?}` restituisce `{job_id, backend, model, seed?}`.
- `GET /jobs/{job_id}` restituisce `{status: running|done|error, ...}` e, a job concluso, i tempi misurati.
- `GET /jobs/{job_id}/video` restituisce l'MP4.

Ogni richiesta porta `Authorization: Bearer <token>`. Il token sta nel secret GitHub `MYSOGNI_API_TOKEN`, che il workflow copia nel secret Modal `mysogni-web-auth` (chiave `API_TOKEN`). Il proxy token di Modal non si usa perché blocca la richiesta preliminare CORS del browser (verificato il 17/11/2026).
