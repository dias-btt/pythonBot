import json
import numpy as np
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")

with open("result.json", "r", encoding="utf-8") as f:
    data = json.load(f)

messages = [
    m.strip()
    for m in data["messages"]
    if isinstance(m, str) and len(m.strip()) > 2
]

print("Encoding messages:", len(messages))

embeddings = model.encode(messages, show_progress_bar=True)

np.save("messages.npy", np.array(messages, dtype=object))
np.save("embeddings.npy", embeddings)

print("Saved index ✔")