import chromadb, glob, os
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
db = chromadb.PersistentClient(path="db").get_or_create_collection("crops")

for f in glob.glob("docs/*.txt"):
    crop = os.path.basename(f).replace(".txt", "")
    text = open(f, encoding="utf-8").read()
    chunks = [c.strip() for c in text.split("\n\n") if c.strip()]
    db.upsert(
        ids=[f"{crop}-{i}" for i in range(len(chunks))],
        documents=chunks,
        embeddings=model.encode(chunks).tolist(),
        metadatas=[{"crop": crop, "source": os.path.basename(f)}] * len(chunks),
    )
    print("loaded", crop, len(chunks), "chunks")