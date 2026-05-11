import chromadb


# chroma_client = chromadb.Client()
chroma_client = chromadb.PersistentClient(path="data/chroma")

collection = chroma_client.get_or_create_collection(name="test")

collection.upsert(
    ids=["id1", "id2", 'id3'],
    documents=[
        "This is a document about pineapple",
        "This is a document about oranges",
        "This is a document about everything but hawaii"
    ]
)

results = collection.query(
    query_texts=["This is a query document about hawaii"], # Chroma will embed this for you
    n_results=2 # how many results to return
)
print(results)
