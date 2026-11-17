# MySogni Web

Pagina web per generare video con MiniMax H3 su GPU remote, senza notebook né sessioni da gestire.

- **Pagina:** `docs/`, pubblicata su GitHub Pages.
- **Backend:** `backend/modal_app.py`, un router web su Modal che passa i lavori a un worker.
- **Stato attuale:** worker di prova su CPU (`MYSOGNI_FAKE_WORKER=1`), che produce un video di test. Nessuna GPU in uso.

## Primo utilizzo

1. Apri la pagina su GitHub Pages: `https://vale717171.github.io/mysogni-web/`.
2. In **Impostazioni** inserisci:
   - l'indirizzo del backend, stampato in fondo al log di **Actions → Deploy backend su Modal** (finisce con `--mysogni-web-api.modal.run`);
   - Token ID (`wk-…`) e secret (`ws-…`) di un proxy token di Modal.
3. **Prova la connessione**, poi genera.

Le impostazioni restano salvate solo nel browser del dispositivo.

## Pubblicazione

Ogni push su `main` ripubblica in automatico:

- la pagina, se cambia `docs/`;
- il backend su Modal, se cambia `backend/`. Servono i secret del repository `MODAL_TOKEN_ID` e `MODAL_TOKEN_SECRET`.

Regole per chi lavora sul codice, persone o agenti: vedi `AGENTS.md`.
