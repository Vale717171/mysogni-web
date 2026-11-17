"""Screenwriter: trasforma un'idea in italiano in un prompt MiniMax H3 (modalità T2VA) in inglese.

Chiama un modello linguistico tramite Cheaper Inference (API compatibile OpenAI) con zero data retention
attiva su ogni richiesta. Né l'idea né il prompt prodotto vengono scritti nei log.
"""

import re

SHOTS = {5: "1 shot (2 at most if the idea really needs a cut)", 10: "2 or 3 shots", 15: "3 or 4 shots"}
WORDS = {5: "90-160", 10: "150-250", 15: "200-320"}

SYSTEM_PROMPT = """You are a screenwriter who turns a short idea, usually written in Italian, into a prompt for the MiniMax H3 text-to-video-with-audio model (T2VA mode).

Output exactly three lines, in English, with nothing before or after them (no markdown, no code fences, no comments):
integrated_multimodal_description: ...
overall_soundscape: ...
non_diegetic_music: ...

Rules for integrated_multimodal_description:
- Start with "[Shot 1]" (it starts at 0.00s and has no timestamp). Each later shot starts with "[Shot N] At 00:SS.mmm," with a single timestamp, never a range; timestamps strictly increase and stay below the clip length.
- First establish the setting (place, time of day, lighting, atmosphere), then describe what visibly and audibly happens in order, as continuous prose.
- Describe the camera in plain language (static, slow push-in, tracking shot, pan, close-up, wide shot). Inside one shot, small reframes are camera motion, not cuts. Between shots use phrasing such as "the camera cuts to".
- Fit the action to the clip length: only what can realistically happen in that time. Do not cram extra events.
- Diegetic sounds tied to on-screen actions (a door opening, footsteps) and any dialogue go inside the shot text, not in the audio fields.
- Include dialogue only if the idea asks for speech. Write it as: (S1) says: <d>[Language] line</d>, using speaker IDs S1, S2..., and keep the language the idea asks for (English if unspecified).
- Stay faithful to the idea: do not add characters, plot events or on-screen text it does not imply. You may add concrete visual detail (wardrobe, materials, light, colors) that makes the scene filmable.
- No negative prompts, no keyword lists such as "4k, masterpiece, cinematic".

Rules for overall_soundscape: 1 to 4 sentences of ambience, sound effects and non-verbal sounds. Write N/A only if the clip is truly silent.
Rules for non_diegetic_music: 1 to 3 sentences describing the score, or N/A. Use N/A unless the idea asks for music or clearly calls for a score."""

FIELDS = ("integrated_multimodal_description:", "overall_soundscape:", "non_diegetic_music:")


def build_messages(idea: str, duration: int) -> list[dict]:
    user = (
        f"Clip length: {duration} seconds (24 fps).\n"
        f"Use {SHOTS[duration]}. Aim for {WORDS[duration]} words in total.\n\n"
        f"Idea:\n{idea.strip()}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def clean_output(text: str, duration: int) -> str:
    """Toglie eventuali recinti markdown e verifica la struttura. Solleva ValueError se non va."""
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text.strip()).strip()
    # Alcuni modelli ragionano ad alta voce prima della risposta: si tiene dal primo campo in poi.
    start = text.find(FIELDS[0])
    if start < 0:
        raise ValueError("Risposta del modello senza il campo integrated_multimodal_description")
    text = text[start:]
    positions = [text.find(f) for f in FIELDS]
    if any(p < 0 for p in positions) or positions != sorted(positions):
        raise ValueError("Risposta del modello senza i tre campi nell'ordine previsto")
    for seconds in re.findall(r"At 00:(\d{2})\.\d{3}", text):
        if int(seconds) >= duration:
            raise ValueError("Il modello ha messo un'inquadratura oltre la durata del video")
    lines = []
    for i, field in enumerate(FIELDS):
        end = positions[i + 1] if i + 1 < len(FIELDS) else len(text)
        value = " ".join(text[positions[i] + len(field):end].split())
        lines.append(f"{field} {value}")
    return "\n".join(lines)
