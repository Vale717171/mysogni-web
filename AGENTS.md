# MySogni Web: istruzioni per gli agenti

Pagina web (GitHub Pages) per generare video con MiniMax H3 su GPU remote. Il piano completo è nel documento "MySogni Web – struttura e primo traguardo"; qui ci sono le regole operative.

## Regole

- Nessuna generazione su GPU, nessun cambio di piano o limite di spesa su Modal o Google Cloud senza il consenso esplicito di Valentino. Il modello `test` non usa GPU e si può collaudare liberamente. Il modello `h3-prism` esiste solo se la variabile di repository `MYSOGNI_GPU_ENABLED` vale `1`; `h3-ultrafast-int8` richiede in più `MYSOGNI_ULTRAFAST_ENABLED=1`, `h3-turbo-bf16` e `h3-quality-bf16` richiedono `MYSOGNI_BF16_ENABLED=1` (ognuno dopo aver scaricato i suoi pesi in mysogni-gpu). Non attivarle e non lanciare lavori GPU senza consenso.
- Nessun segreto nel repository: il repository è pubblico. Token e chiavi stanno solo nei secret di GitHub o di Modal.
- Prompt e video non vanno mai committati né scritti nei log di GitHub Actions.
- Lavora su un ramo separato e apri una pull request; `main` pubblica in automatico pagina e backend.
- Distingui sempre tra prova simulata (worker finto), prova reale e ipotesi.

- La pagina conserva nel browser gli ultimi 20 lavori (al massimo 7 giorni) e dopo un ricaricamento riprende a seguirli. Gli errori temporanei del router (rete, 5xx, prelazione) non chiudono il lavoro: la pagina riprova per 15 minuti. Il router è `nonpreemptible`.

## Mappa

- `docs/`: la pagina statica pubblicata da `.github/workflows/pages.yml`.
- `backend/modal_app.py`: router web (CPU) e worker di prova, pubblicati da `.github/workflows/deploy-modal.yml`.
- Worker GPU: repository privato `Vale717171/mysogni-gpu`, app Modal `mysogni-gpu`, classe `Generator`. Il router lo chiama per nome con `modal.Cls.from_name`; il codice PRISM non va copiato qui, perché questo repository è pubblico.
- `backend/worker/`: segnaposto per il futuro modello UltraFast (script di Colab di MySogni).

## Contratto dell'API

- `GET /health` restituisce `{ok, gpu_enabled, models, screenwriter: {enabled, model}}`; la pagina costruisce da qui l'elenco dei modelli e delle risoluzioni.
- `POST /jobs` con `{prompt, duration, model, backend, profile?, steps?, resolution?, m3_strength?, seed?}` restituisce `{job_id, backend, model, seed?}`. Modelli, profili, risoluzioni e opzioni ammessi stanno in `GPU_MODELS` di `backend/modal_app.py` e arrivano alla pagina da `/health`: la pagina non ha elenchi propri.
- `GET /jobs/{job_id}` restituisce `{status: running|done|error, ...}` e, a job concluso, i tempi misurati.
- `GET /jobs/{job_id}/video` restituisce l'MP4.
- `POST /screenwriter` con `{idea, duration}` restituisce `{prompt, model, duration, prompt_source}`: prompt H3 in inglese (tre campi T2VA) scritto da un modello linguistico via Cheaper Inference. Il system prompt è quello privato di screenwriter-h3, copiato dal workflow di `mysogni-gpu` nel Volume `mysogni-private-config` e letto a ogni richiesta; se manca si usa quello di riserva in `backend/screenwriter.py` (`prompt_source: fallback`). Non copiare qui il prompt privato. Le richieste vanno sempre con `"zdr": true`. Se manca un fornitore con zero data retention risponde 503: non si ripiega mai su fornitori senza ZDR. La chiave sta nel secret GitHub `CHEAPERINFERENCE_API_KEY`, copiato nel secret Modal `mysogni-web-llm` (chiave `LLM_API_KEY`); il modello si cambia con la variabile di repository `MYSOGNI_LLM_MODEL` (predefinito `deepseek-v4-flash-0731`).

Ogni richiesta porta `Authorization: Bearer <token>`. Il token sta nel secret GitHub `MYSOGNI_API_TOKEN`, che il workflow copia nel secret Modal `mysogni-web-auth` (chiave `API_TOKEN`). Il proxy token di Modal non si usa perché blocca la richiesta preliminare CORS del browser (verificato il 17/11/2026).
