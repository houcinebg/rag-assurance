"""Cœur du système: conditions générales -> réponse avec citations vérifiées."""
import json
import os
import re
import sqlite3
from pathlib import Path
import string

from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

MIN_SCORE = float(os.getenv("MIN_SCORE", "0.01"))  # sous ce seuil, le LLM n'est pas appelé (scores TF-IDF typiques: 0,03 à 0,13)
ARTICLE = re.compile(r"^\s*(Article\s+\d+[A-Za-z]?(?:\.\d+)*)\s*[-–:.]?\s*(.*)$", re.I | re.M)


# ---------- 1. Lecture et découpage par article ----------
def read_text(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() != ".pdf":
        return p.read_text(encoding="utf-8")
    try:
        import pymupdf
        with pymupdf.open(p) as doc:
            return "\n".join(page.get_text("text", sort=True) for page in doc)
    except ImportError:
        return "\n".join(page.extract_text() or "" for page in PdfReader(p).pages)


MAX_ARTICLE_CHARS = 6000  # au-delà, l'article est redécoupé (sinon il écrase la recherche)
MIN_ARTICLE_CHARS = 150  # en dessous: ligne de sommaire ou renvoi, pas un article


def _windows(text: str, contract: str, size: int = 1500) -> list[dict]:
    """Secours sans 'Article N': regroupe des paragraphes entiers, sans couper au milieu d'une phrase."""
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    blocks, cur = [], ""
    for p in parts:
        if cur and len(cur) + len(p) > size:
            blocks.append(cur)
            cur = ""
        cur = f"{cur}\n\n{p}".strip()
    if cur:
        blocks.append(cur)
    return [{"contract": contract, "id": f"§{i + 1}", "title": "", "text": b} for i, b in enumerate(blocks)]


def split_articles(text: str, contract: str) -> list[dict]:
    """Un chunk = un article. Ignore le sommaire, garde la version la plus complète de chaque numéro."""
    hits = list(ARTICLE.finditer(text))
    best: dict[str, dict] = {}
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        body = text[m.start():end].strip()
        if len(body) < MIN_ARTICLE_CHARS:
            continue  # ligne de sommaire
        art_id = re.sub(r"\s+", " ", m.group(1)).title()
        if art_id not in best or len(body) > len(best[art_id]["text"]):
            best[art_id] = {"contract": contract, "id": art_id, "title": m.group(2).strip(), "text": body}
    if len(best) < 3:
        return _windows(text, contract)
    out = []
    for c in sorted(best.values(), key=lambda c: [int(n) for n in re.findall(r"\d+", c["id"])] + [c["id"]]):
        if len(c["text"]) <= MAX_ARTICLE_CHARS:
            out.append(c)
            continue
        for k, part in enumerate(_windows(c["text"], contract, size=4000), 1):
            out.append({**c, "id": f"{c['id']} §{k}", "text": part["text"]})
    return out


# ---------- 2. Récupération (TF-IDF: simple, sans service externe) ----------
class Index:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, strip_accents="unicode")
        self.matrix = self.vec.fit_transform([f"{c['title']} {c['text']}" for c in chunks])

    def search(self, query: str, k: int = 5) -> list[tuple[dict, float]]:
        scores = cosine_similarity(self.vec.transform([query]), self.matrix)[0]
        order = scores.argsort()[::-1][:k]
        return [(self.chunks[i], float(scores[i])) for i in order if scores[i] > 0]


# ---------- 3. Réponse en trois états, citations vérifiées ----------
SYSTEM = """Tu analyses si un sinistre est couvert, UNIQUEMENT à partir des extraits de contrat fournis.
Réponds par un JSON strict, sans texte autour:
{"verdict": "couvert" | "non_couvert" | "ambigu",
 "raisonnement": "2 à 4 phrases",
 "citations": [{"article": "Article 3", "extrait": "copie EXACTE d'un passage de cet article"}],
 "infos_manquantes": ["faits que l'assuré devrait préciser"]}
Règles: n'invente aucune clause. Si les extraits ne permettent pas de trancher (clause absente,
conditions non précisées, exclusion possible), réponds "ambigu". Un "ambigu" argumenté vaut mieux
qu'un verdict non étayé. Tout verdict couvert/non_couvert exige au moins une citation."""


def _norm(s: str) -> str:
    s=re.sub(r"\s+", " ", s).strip().lower()
    return s.translate(str.maketrans('', '', string.punctuation))

def _json(raw: str):
    clean = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        raise ValueError(f"réponse du modèle non exploitable ({e}). Début reçu: {raw[:200]!r}") from e


def _call(system: str, user: str, obj: bool = False) -> str:
    base = os.getenv("LLM_BASE_URL")
    if not base:
        raise ValueError("LLM_BASE_URL n'est pas défini dans les variables d'environnement.")

    from openai import OpenAI
    client = OpenAI(base_url=base, api_key=os.getenv("LLM_API_KEY", "none"))
    
    kw = dict(model=os.environ["LLM_MODEL"], temperature=0.1,
              messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
              
    if os.getenv("LLM_REASONING_EFFORT"):
        kw["reasoning_effort"] = os.environ["LLM_REASONING_EFFORT"]
        
    tokens = int(os.getenv("LLM_MAX_TOKENS", "4000"))
    
    for _ in range(3):
        try:  # mode JSON si le fournisseur l'accepte
            r = client.chat.completions.create(max_tokens=tokens, **kw,
                                               **({"response_format": {"type": "json_object"}} if obj else {}))
        except Exception as e:
            if not obj:
                raise
            # Si le mode JSON plante, on réessaie sans
            r = client.chat.completions.create(max_tokens=tokens, **kw)
            
        if r.choices[0].finish_reason != "length":
            break
        tokens *= 2
        
    return r.choices[0].message.content or ""

EXPAND = """Tu aides une recherche dans un contrat d'assurance habitation. Réécris la situation en 15 à 25 mots-clés
tels qu'ils apparaissent dans un contrat (garantie, événement, condition, exclusion, lieu, bien concerné).
Réponds uniquement par les mots-clés, séparés par des espaces."""


def answer(question: str, index: Index, k: int = 6) -> dict:
    try:  # les mots de la question ne sont pas ceux du contrat: on ajoute le vocabulaire contractuel
        expansion = _call(EXPAND, question).strip()[:400] if os.getenv("LLM_EXPAND", "1") == "1" else ""
    except Exception:
        expansion = ""  # sans élargissement, la recherche reste possible
    hits = index.search(f"{question} {expansion}", k)
    if not hits or hits[0][1] < MIN_SCORE:
        return {"verdict": "ambigu", "raisonnement": "La recherche n'a retrouvé aucun passage assez proche de cette situation. Cela ne prouve pas que le contrat n'en traite pas: reformuler la question peut aider.",
                "citations": [], "infos_manquantes": [], "sources": [], "garde_fou": "retrieval_vide",
                "requete_etendue": expansion}

    context = "\n\n".join(f"[{c['id']}] {c['title']}\n{c['text']}" for c, _ in hits)
    out = _json(_call(SYSTEM, f"Extraits:\n{context}\n\nSituation: {question}", obj=True))

    # Garde-fou: chaque citation doit exister mot pour mot dans l'article cité
    by_id = {_norm(c["id"]): c for c, _ in hits}
    valid = []
    for cit in out.get("citations", []):
        chunk = by_id.get(_norm(cit.get("article", "")))
        if chunk and _norm(cit.get("extrait", "")) and _norm(cit["extrait"]) in _norm(chunk["text"]):
            valid.append(cit)
    out["citations"] = valid
    out["requete_etendue"] = expansion
    out["sources"] = [{"article": c["id"], "titre": c["title"], "score": round(s, 2)} for c, s in hits]
    out["garde_fou"] = None
    if out.get("verdict") in ("couvert", "non_couvert") and not valid:
        out.update(verdict="ambigu", garde_fou="citation_non_verifiee",
                   raisonnement="Verdict rétrogradé: aucune citation vérifiable. " + out.get("raisonnement", ""))
    return out


# ---------- 4. Extraction structurée vers SQL (pour passer à des centaines de contrats) ----------
EXTRACT = """Extrais du contrat les éléments structurés. JSON strict, une liste:
[{"type": "garantie"|"exclusion"|"plafond"|"franchise", "libelle": "...", "valeur": "montant ou condition, sinon vide",
  "article": "Article N", "extrait": "copie EXACTE du passage"}]"""


def extract_to_sql(chunks: list[dict], db_path: str = "contrats.db") -> int:
    contract = chunks[0]["contract"]
    full = "\n\n".join(c["text"] for c in chunks)
    batches, cur, size = [], [], 0
    for c in chunks:
        if cur and size + len(c["text"]) > 12000:
            batches.append("\n\n".join(cur))
            cur, size = [], 0
        cur.append(c["text"])
        size += len(c["text"])
    if cur:
        batches.append("\n\n".join(cur))
    rows = []
    for b in batches[: int(os.getenv("EXTRACT_MAX_BATCHES", "10"))]:  # plafond d'appels (quotas gratuits)
        got = _json(_call(EXTRACT, b))
        rows += next((v for v in got.values() if isinstance(v, list)), []) if isinstance(got, dict) else got
    con = sqlite3.connect(db_path)
    con.execute("""CREATE TABLE IF NOT EXISTS clauses(contrat TEXT, type TEXT, libelle TEXT,
                   valeur TEXT, article TEXT, extrait TEXT, verifie INTEGER)""")
    con.execute("DELETE FROM clauses WHERE contrat = ?", (contract,))
    text_n = _norm(full)
    for r in rows:
        ok = int(_norm(r.get("extrait", "")) in text_n)  # trace vérifiable ou non
        con.execute("INSERT INTO clauses VALUES (?,?,?,?,?,?,?)",
                    (contract, r["type"], r["libelle"], r.get("valeur", ""), r["article"], r["extrait"], ok))
    con.commit()
    con.close()
    return len(rows)


def read_clauses(db_path: str = "contrats.db"):
    import pandas as pd
    if not Path(db_path).exists():
        return pd.DataFrame()
    with sqlite3.connect(db_path) as con:
        return pd.read_sql("SELECT * FROM clauses ORDER BY contrat, type", con)
