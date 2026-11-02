"""Évalue le système sur un jeu de questions étiquetées. Reprenable: adapté aux quotas gratuits.

  python eval/run_eval.py --retrieval-only
  python eval/run_eval.py --tag test --max-calls 10 --shuffle

Chaque question répondue est sauvegardée dans eval/cache_<tag>.jsonl. Un quota atteint (429) arrête
proprement l'exécution. Après une modification du code, utiliser un autre --tag (ex. test2).
Pour économiser les appels: export LLM_EXPAND=0 (une seule requête par question au lieu de deux).
"""
import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import core  # noqa: E402


def base(i):
    return re.sub(r" §\d+$", "", i)


def rate(n, d):
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "n/a"


def is_quota(e: Exception) -> bool:
    m = str(e).lower()
    return "429" in m or "quota" in m or "rate limit" in m or "resource_exhausted" in m


def main():
    ap = argparse.ArgumentParser()
    # Valeurs par défaut mises à jour pour ton projet actuel
    ap.add_argument("--contract", default=str(ROOT / "data" / "mutuelle.pdf"))
    ap.add_argument("--questions", default=str(ROOT / "eval" / "questions_mutuelle.json"))
    ap.add_argument("--k", type=int, default=6)
    ap.add_argument("--retrieval-only", action="store_true")
    ap.add_argument("--tag", default="run", help="nom de la série (ex: final, test...)")
    ap.add_argument("--max-calls", type=int, default=0, help="nb max de questions envoyées au modèle (0 = toutes)")
    ap.add_argument("--sleep", type=float, default=5.0, help="secondes entre deux questions")
    ap.add_argument("--shuffle", action="store_true",
                    help="ordre aléatoire fixe (graine 0): un arrêt partiel reste représentatif de tous les thèmes")
    ap.add_argument("--retries", type=int, default=2, help="essais après un 429 (limite par minute) avant d'arrêter")
    ap.add_argument("--retry-wait", type=float, default=65.0, help="secondes d'attente avant un nouvel essai")
    a = ap.parse_args()

    questions = json.loads(Path(a.questions).read_text(encoding="utf-8"))
    if a.shuffle:
        random.Random(0).shuffle(questions)
    chunks = core.split_articles(core.read_text(a.contract), Path(a.contract).name)
    index = core.Index(chunks)
    cache_path = ROOT / "eval" / f"cache_{a.tag}.jsonl"
    cache = {}
    if cache_path.exists() and not a.retrieval_only:
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                cache[r["id"]] = r["res"]

    rows, stop, calls, errors = [], None, 0, 0
    for item in questions:
        exp = item["articles"]
        if a.retrieval_only:
            hits = index.search(item["q"], a.k)
            got = list(dict.fromkeys(base(c["id"]) for c, _ in hits))
            rows.append({"id": item["id"], "attendu": item["verdict"], "articles_attendus": exp, "sources": got,
                         "hit": all(e in got for e in exp) if exp else None,
                         "top": round(hits[0][1], 3) if hits else 0.0})
            continue
        res = cache.get(item["id"])
        if res is None:
            if stop:
                continue
            if a.max_calls and calls >= a.max_calls:
                stop = "plafond --max-calls atteint"
                continue
            for attempt in range(a.retries + 1):
                try:
                    res = core.answer(item["q"], index, a.k)
                    break
                except Exception as e:
                    if is_quota(e):
                        if attempt < a.retries:  # souvent une limite par minute: on attend puis on réessaie
                            print(f"  quota (429) à la question {item['id']}: attente {a.retry_wait:.0f}s, "
                                  f"nouvel essai {attempt + 1}/{a.retries}")
                            time.sleep(a.retry_wait)
                            continue
                        stop = "quota du fournisseur atteint (429), même après attente"
                    else:
                        errors += 1
                        print(f"  question {item['id']}: erreur non sauvegardée ({str(e)[:120]})")
                    break
            if res is None:
                continue
            calls += 1
            with cache_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"id": item["id"], "res": res}, ensure_ascii=False) + "\n")
            time.sleep(a.sleep)
        got = list(dict.fromkeys(base(s_["article"]) for s_ in res.get("sources", [])))
        rows.append({"id": item["id"], "attendu": item["verdict"], "articles_attendus": exp, "sources": got,
                     "hit": all(e in got for e in exp) if exp else None,
                     "obtenu": res["verdict"], "garde_fou": res.get("garde_fou"),
                     "cites": list(dict.fromkeys(base(c["article"]) for c in res.get("citations", [])))})

    rows.sort(key=lambda r: r["id"])
    n_q = len(questions)
    out = ["# Rapport d'évaluation", "",
           f"Contrat: `{Path(a.contract).name}` · série `{a.tag}` · k={a.k} · "
           f"**{len(rows)}/{n_q} questions évaluées**" + (" · ordre aléatoire (graine 0)" if a.shuffle else "")
           + (f" · arrêt: {stop}" if stop else ""), ""]
    with_art = [r for r in rows if r["hit"] is not None]
    out.append(f"- **Récupération (hit@{a.k})**: {rate(sum(r['hit'] for r in with_art), len(with_art))} "
               "des questions dont tous les articles attendus sont retrouvés")
    if not a.retrieval_only and rows:
        ok = [r for r in rows if r["obtenu"] == r["attendu"]]
        firm = [r for r in rows if r["obtenu"] in ("couvert", "non_couvert")]
        over = [r for r in firm if r["obtenu"] != r["attendu"]]
        needless = [r for r in rows if r["obtenu"] == "ambigu" and r["attendu"] != "ambigu"]
        amb = [r for r in rows if r["attendu"] == "ambigu"]
        cite_ok = [r for r in firm if set(r["cites"]) & set(r["articles_attendus"])]
        out += [
            f"- **Verdict correct**: {rate(len(ok), len(rows))}",
            f"- **Erreurs assurées** (verdict ferme faux, le pire cas): {rate(len(over), len(firm))} des verdicts fermes",
            f"- **Abstentions inutiles** (ambigu alors que le contrat tranche): {rate(len(needless), len(rows))}",
            f"- **Ambiguïtés bien détectées**: {rate(sum(r['obtenu'] == 'ambigu' for r in amb), len(amb))}",
            f"- **Verdicts fermes citant un bon article**: {rate(len(cite_ok), len(firm))}",
            f"- **Garde-fous déclenchés**: {sum(1 for r in rows if r.get('garde_fou'))}",
        ]
    out += ["", "## Détail", ""]
    if a.retrieval_only:
        out += ["| id | attendus | récupérés | hit |", "|---|---|---|---|"]
        out += [f"| {r['id']} | {', '.join(r['articles_attendus']) or '-'} | {', '.join(r['sources'])} | {r['hit']} |"
                for r in rows]
    else:
        out += ["| id | attendu | obtenu | citations | garde-fou | hit |", "|---|---|---|---|---|---|"]
        out += [f"| {r['id']} | {r['attendu']} | {r['obtenu']} | {', '.join(r['cites']) or '-'} "
                f"| {r['garde_fou'] or '-'} | {r['hit']} |" for r in rows]
    report = "\n".join(out)
    suffix = "retrieval" if a.retrieval_only else a.tag
    (ROOT / "eval" / f"report_{suffix}.md").write_text(report, encoding="utf-8")
    print(report)
    if stop and not a.retrieval_only:
        print(f"\n>>> Arrêt: {stop}. {n_q - len(rows) - errors} questions restantes. "
              f"Relance la même commande plus tard: elle reprend là où elle s'est arrêtée.")


if __name__ == "__main__":
    main()
