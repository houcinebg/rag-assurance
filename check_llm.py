"""Vérifie la connexion au fournisseur LLM avant de lancer l'application.

  export LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
  export LLM_API_KEY=<clé AI Studio>
  python check_llm.py --all      # teste chaque modèle de texte et dit lesquels répondent
  export LLM_MODEL=<un modèle qui a répondu OK>
  python check_llm.py            # appel test détaillé du modèle choisi
"""
import json
import os
import sys

from openai import OpenAI

base, key, model = os.getenv("LLM_BASE_URL"), os.getenv("LLM_API_KEY"), os.getenv("LLM_MODEL")
if not base or not key:
    sys.exit("Définir LLM_BASE_URL et LLM_API_KEY (voir l'en-tête de ce fichier).")

client = OpenAI(base_url=base, api_key=key, max_retries=0)
PROMPT = [{"role": "user", "content": 'Réponds uniquement par ce JSON: {"ok": true}'}]
SKIP = ("image", "audio", "tts", "live", "omni", "embedding", "imagen", "veo", "robotics", "computer", "aqa")


def describe(e: Exception) -> str:
    """Message complet: code HTTP, adresse appelée et corps de la réponse."""
    r = getattr(e, "response", None)
    if r is None:
        return str(e)
    return f"HTTP {r.status_code} sur {r.request.url}\n  corps: {r.text[:400] or '(vide)'}"


def try_model(name: str):
    return client.chat.completions.create(model=name, temperature=0, max_tokens=200, messages=PROMPT)


ids = []
try:
    ids = sorted(m.id.removeprefix("models/") for m in client.models.list())
except Exception as e:
    print(f"Liste des modèles impossible:\n  {describe(e)}")

if "--all" in sys.argv:
    cands = [i for i in ids if "gemini" in i and not any(s in i for s in SKIP)]
    print(f"Test de {len(cands)} modèles de texte (un appel chacun):\n")
    for name in cands:
        try:
            out = (try_model(name).choices[0].message.content or "").strip().replace("\n", " ")[:40]
            print(f"  OK       {name}  -> {out!r}")
        except Exception as e:
            first = describe(e).splitlines()
            print(f"  ÉCHEC    {name}  {first[0][:90]}")
    sys.exit("\nChoisis un modèle OK stable (sans « preview » ni « latest »), puis: export LLM_MODEL=<nom>")

if not model:
    sys.exit("Définir LLM_MODEL, ou lancer: python check_llm.py --all")

try:
    txt = try_model(model).choices[0].message.content or ""
    print(f"Réponse de {model}: {txt!r}")
    try:
        json.loads(txt.strip().strip("`").removeprefix("json").strip())
        print("JSON valide: le modèle respecte la consigne.")
    except Exception:
        print("Attention: réponse non JSON. L'application nettoie les blocs ```json, mais vérifie.")
except Exception as e:
    sys.exit(f"Appel impossible pour {model}:\n  {describe(e)}")
