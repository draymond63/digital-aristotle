from enum import StrEnum


class Collection(StrEnum):
    INSIGHTS = "insights"
    CONFUSIONS = "confusions"
    PREVIOUS_ASKS = "previous_asks"
    SUCCESSFUL_EXPLANATIONS = "successful_explanations"
    LEARNING_PREFERENCES = "learning_preferences"


class SemanticDatabase:
    def __init__(self, path: str = "data/chroma"):
        from chromadb import PersistentClient

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

    def query_pretty(self, *args, max_dist=0.8, **kwargs):
        response = self.query(*args, **kwargs)
        pretty = []
        results = [(doc, dist) for doc, dist in zip(response["documents"][0], response["distances"][0]) if dist <= max_dist]
        if not len(results):
            return ""
        for doc, dist in results:
            pretty.append(f"{doc} (dist: {dist:3f})")
        return "\n".join(pretty)

    def query(self, collection_name: Collection, query_texts: list[str], **kwargs):
        collection = self.collection(collection_name)
        results = collection.query(query_texts=query_texts, **kwargs)
        return results

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
