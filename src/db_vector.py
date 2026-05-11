import chromadb
from enum import StrEnum
from datetime import datetime


class Collection(StrEnum):
    INSIGHTS = "insights"
    CONFUSIONS = "confusions"
    PREVIOUS_ASKS = "previous_asks"


class SemanticDatabase:
    def __init__(self, path: str = "data/chroma"):
        self.client = chromadb.PersistentClient(path=path)

    def log_ask(self, question: str):
        self.add(
            collection_name=Collection.PREVIOUS_ASKS,
            ids=[str(datetime.now().timestamp())],
            documents=[question]
        )

    def add(self, collection_name: Collection, ids: list[str], documents: list[str]):
        collection = self.client.get_or_create_collection(name=collection_name.v)
        collection.upsert(ids=ids, documents=documents)

    def query(self, collection_name: Collection, query_texts: list[str], n_results: int = 5):
        collection = self.client.get_collection(name=collection_name)
        results = collection.query(query_texts=query_texts, n_results=n_results)
        return results


def example():
    """Example related to inductance and spin"""
    db = SemanticDatabase()
    db.add(
        collection_name="memories",
        ids=["1", "2", "3"],
        documents=[
            "Inductance is the property of an electrical conductor by which a change in current through it induces an electromotive force (voltage) in both the conductor itself and in any nearby conductors.",
            "Spin is a fundamental property of particles, akin to charge and mass, that describes their intrinsic angular momentum. It is quantized, meaning it can only take on certain discrete values.",
            "The relationship between inductance and spin is not direct, but both concepts are crucial in understanding electromagnetic phenomena and quantum mechanics."
        ]
    )
