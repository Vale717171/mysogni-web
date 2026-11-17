# MySogni Web

Pagina web per generare video con MiniMax H3 su GPU remote, senza notebook né sessioni da gestire.

- **Pagina:** `docs/`, pubblicata su GitHub Pages.
- **Backend:** `backend/modal_app.py`, un router web su Modal che passa i lavori a un worker.
- **Stato attuale:** worker di prova su CPU (`MYSOGNI_FAKE_WORKER=1`), che produce un video di test. Nessuna GPU in uso.

## Primo utilizzo

1. Apri la pagina su GitHub Pages: `https://vale717171.github.io/mysogni-web/`.
2. In **Impostazioni** inserisci:
   - l'indirizzo del backend: `https://valentinoricco--mysogni-web-api.us-east.modal.run` (è anche in fondo al log di **Actions → Deploy backend su Modal**);
   - il token di accesso, cioè lo stesso valore del secret `MYSOGNI_API_TOKEN`.
3. **Prova la connessione**, poi genera.

Le impostazioni restano salvate solo nel browser del dispositivo.

## Pubblicazione

Ogni push su `main` ripubblica in automatico:

- la pagina, se cambia `docs/`;
- il backend su Modal, se cambia `backend/`. Servono i secret del repository `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` e `MYSOGNI_API_TOKEN`.

Regole per chi lavora sul codice, persone o agenti: vedi `AGENTS.md`.
