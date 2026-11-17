# Worker H3

Qui arriverà la ricetta reale, portata da MySogni (`colab/ultrafast_remote`):

- `h3_ultrafast.json`: workflow ComfyUI di UltraFast NVFP4;
- `models.lock.json`: per ogni peso, repository e revisione Hugging Face più SHA-256.

Il worker GPU girerà su RTX PRO 6000 e leggerà i pesi da un Volume Modal. Finché questa cartella è vuota, `modal_app.py` usa il worker di prova su CPU.
