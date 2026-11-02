import os
import shutil
from pathlib import Path
from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import core

app = FastAPI(title="RAG Assurance - Mutuelle de Poitiers")

CURRENT_INDEX = None


@app.on_event("startup")
def startup_event():
    global CURRENT_INDEX
    pdf_path = Path("data/mutuelle.pdf")
    if pdf_path.exists():
        print(f"Chargement de l'index pour {pdf_path}...")
        chunks = core.split_articles(core.read_text(str(pdf_path)), pdf_path.name)
        CURRENT_INDEX = core.Index(chunks)
        print(f"Index charge ({len(chunks)} articles).")
    else:
        print("Attention: data/mutuelle.pdf introuvable.")


class QueryRequest(BaseModel):
    question: str
    k: int = 6


@app.post("/api/answer")
def answer_question(req: QueryRequest):
    if not CURRENT_INDEX:
        return {"error": "Aucun contrat charge sur le serveur."}
    try:
        return core.answer(req.question, CURRENT_INDEX, k=req.k)
    except Exception as e:
        if "429" in str(e) or "RateLimit" in str(e):
            return {
                "verdict": "ambigu", 
                "raisonnement": "L'API est temporairement surchargee (limite de requetes gratuite atteinte). Veuillez patienter une minute et reessayer.",
                "citations": [],
                "infos_manquantes": [],
                "garde_fou": "rate_limit"
            }
        return {"error": f"Erreur serveur : {str(e)}"}


@app.post("/api/upload")
def upload_contract(file: UploadFile = File(...)):
    global CURRENT_INDEX
    file_location = f"data/{file.filename}"
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    chunks = core.split_articles(core.read_text(file_location), file.filename)
    CURRENT_INDEX = core.Index(chunks)
    return {"info": f"Contrat {file.filename} charge ({len(chunks)} articles)."}


app.mount("/", StaticFiles(directory="app/web", html=True), name="web")
