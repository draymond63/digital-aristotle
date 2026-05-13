from chromadb import PersistentClient, QueryResult
from enum import StrEnum
from datetime import datetime


class Collection(StrEnum):
    INSIGHTS = "insights"
    CONFUSIONS = "confusions"
    PREVIOUS_ASKS = "previous_asks"


class SemanticDatabase:
    def __init__(self, path: str = "data/chroma"):
        self.client = PersistentClient(path=path)

    def log_ask(self, msg: str, session_id: int):
        self.add(
            collection_name=Collection.PREVIOUS_ASKS,
            ids=[str(session_id)],
            documents=[msg]
        )

    def find_asks(self, query: str, max_dist=0.5) -> list[str]:
        response = self.query(
            collection_name=Collection.PREVIOUS_ASKS,
            query_texts=[query],
        )
        docs = response["documents"][0]
        dists = response["distances"][0]
        return [doc for doc, dist in zip(docs, dists) if dist <= max_dist]

    def add(self, collection_name: Collection, ids: list[str], documents: list[str]):
        collection = self.collection(collection_name)
        collection.upsert(ids=ids, documents=documents)

    def query(self, collection_name: Collection, query_texts: list[str], **kwargs):
        collection = self.collection(collection_name)
        results = collection.query(query_texts=query_texts, **kwargs)
        return QueryResult(results)

    def collection(self, collection_name: Collection):
        return self.client.get_or_create_collection(name=collection_name.value)


def example():
    """Example related to inductance and spin"""
    db = SemanticDatabase()
    db.add(
        collection_name=Collection.INSIGHTS,
        ids=["1", "2"],
        documents=[
            "Inductance is the property of an electrical conductor by which a change in current flowing through it induces an electromotive force (voltage) in both the conductor itself and in any nearby conductors.",
            "Spin is a fundamental property of particles, akin to charge and mass, that describes their intrinsic angular momentum."
        ]
    )
    db.add(
        collection_name=Collection.PREVIOUS_ASKS,
        ids=["3"],
        documents=["Why is inductance important in electrical circuits?"]
    )
    return db

if __name__ == "__main__":
    db = example()
    r = db.find_asks("What is inductance?")
    print(r)
