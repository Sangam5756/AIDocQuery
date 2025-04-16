import os
import faiss
import numpy as np
import pickle
from flask import Flask, request, jsonify
from pdfminer.high_level import extract_text
import cohere
from dotenv import load_dotenv

app = Flask(__name__)

load_dotenv()

cohere_api_key = os.getenv("COHERE_API_KEY")
cohere_client = cohere.Client(cohere_api_key)

embedding_dim = 4096

if not os.path.exists("uploads"):
    os.makedirs("uploads")

if os.path.exists("faiss_index.index"):
    index = faiss.read_index("faiss_index.index")
else:
    index = faiss.IndexFlatL2(embedding_dim)

if os.path.exists("documents.pkl"):
    with open("documents.pkl", "rb") as f:
        documents = pickle.load(f)
else:
    documents = []


def extract_text_from_pdf(pdf_path):
    return extract_text(pdf_path)


def get_embeddings(text):
    response = cohere_client.embed(texts=[text])
    return response.embeddings[0]


@app.route("/upload", methods=["POST"])
def upload_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]

    if file and file.filename.endswith(".pdf"):
        file_path = os.path.join("uploads", file.filename)
        file.save(file_path)

        text = extract_text_from_pdf(file_path)
        documents.append(text)

        embedding = get_embeddings(text)
        if len(embedding) != embedding_dim:
            return (
                jsonify(
                    {
                        "error": f"Embedding dimension mismatch. Expected {embedding_dim}, got {len(embedding)}"
                    }
                ),
                400,
            )

        index.add(np.array([embedding]).astype("float32"))

        faiss.write_index(index, "faiss_index.index")
        with open("documents.pkl", "wb") as f:
            pickle.dump(documents, f)

        return jsonify({"message": "PDF uploaded and indexed!"}), 200

    return jsonify({"error": "Invalid file type"}), 400


@app.route("/ask", methods=["POST"])
def ask_question():
    query = request.json.get("query")

    if not query:
        return jsonify({"error": "No query provided"}), 400

    # Get embedding for the query
    query_embedding = get_embeddings(query)
    D, I = index.search(np.array([query_embedding]).astype("float32"), 1)

    if I[0][0] == -1 or len(documents) == 0:
        return jsonify({"error": "No documents indexed yet."}), 400

    # Fetch the relevant document
    relevant_doc = documents[I[0][0]]

    # Prompt with strict instruction to stay within document
    prompt = f"""
        You are an assistant answering questions based strictly on the provided document content.

        If the answer is not clearly mentioned in the context, reply with "Not found in the document."

Context:
\"\"\"
{relevant_doc}
\"\"\"

Question: {query}
Answer:
    """

    response = cohere_client.generate(
        model="command-xlarge", prompt=prompt.strip(), max_tokens=150
    )
    answer = response.generations[0].text.strip()

    return jsonify({"answer": answer})


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
