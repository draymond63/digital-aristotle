from enum import StrEnum
from hashlib import sha1


class Collection(StrEnum):
    INSIGHTS = "insights"
    CONFUSIONS = "confusions"
    PARTIAL_UNDERSTANDINGS = "partial_understandings"
    PREVIOUS_ASKS = "previous_asks"
    SUCCESSFUL_EXPLANATIONS = "successful_explanations"
    LEARNING_PREFERENCES = "learning_preferences"


class MemoryKind(StrEnum):
    INSIGHT = "insights"
    CONFUSION = "confusions"
    PARTIAL_UNDERSTANDING = "partial_understandings"
    SUCCESSFUL_EXPLANATION = "successful_explanations"
    LEARNING_PREFERENCE = "learning_preferences"

    @property
    def memory_type(self) -> str:
        return self.value.removesuffix("s")

    @property
    def collection(self) -> Collection:
        return Collection(self.value)

    @classmethod
    def vector_collections(cls) -> tuple[Collection, ...]:
        return tuple(kind.collection for kind in cls)


class SemanticDatabase:
    def __init__(self, path: str = "data/chroma"):
        from chromadb import PersistentClient

        self.client = PersistentClient(path=path)

    def log_ask(self, msg: str, session_id: int, user_id: str | None = None):
        ask_id = sha1(f"{user_id or ''}:{session_id}:{msg}".encode("utf-8")).hexdigest()[:16]
        self.add(
            collection_name=Collection.PREVIOUS_ASKS,
            ids=[f"{session_id}-{ask_id}"],
            documents=[msg],
            metadatas=[self._metadata(user_id=user_id, session_id=str(session_id))],
        )

    def find_asks(self, query: str, max_dist=0.5, user_id: str | None = None) -> list[str]:
        response = self.query(
            collection_name=Collection.PREVIOUS_ASKS,
            query_texts=[query],
            user_id=user_id,
        )
        docs = response["documents"][0]
        dists = response["distances"][0]
        return [doc for doc, dist in zip(docs, dists) if dist <= max_dist]

    def add(
        self,
        collection_name: Collection,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict] | None = None,
    ):
        collection = self.collection(collection_name)
        kwargs = {"ids": ids, "documents": documents}
        if metadatas is not None:
            kwargs["metadatas"] = metadatas
        collection.upsert(**kwargs)

    def ids_for_metadata(self, collection_name: Collection, **metadata_filter) -> list[str]:
        collection = self.collection(collection_name)
        ids = []
        if "user_id" in metadata_filter:
            response = collection.get(where=self._user_where(metadata_filter["user_id"]), include=["metadatas"])
        else:
            response = collection.get(include=["metadatas"])
        for item_id, metadata in zip(response.get("ids") or [], response.get("metadatas") or []):
            if all(metadata.get(key) == value for key, value in metadata_filter.items()):
                ids.append(item_id)
        return ids

    def delete_ids(self, collection_name: Collection, ids: list[str]):
        if not ids:
            return
        self.collection(collection_name).delete(ids=ids)

    def query_pretty(self, *args, max_dist=0.8, user_id: str | None = None, **kwargs):
        if user_id:
            kwargs["user_id"] = user_id
        response = self.query(*args, **kwargs)
        pretty = []
        results = []
        seen = set()
        for docs, dists in zip(response["documents"], response["distances"]):
            for doc, dist in zip(docs, dists):
                if dist <= max_dist and doc not in seen:
                    results.append((doc, dist))
                    seen.add(doc)
        if not len(results):
            return ""
        for doc, dist in sorted(results, key=lambda item: item[1]):
            pretty.append(f"{doc} (dist: {dist:3f})")
        return "\n".join(pretty)

    def query(self, collection_name: Collection, query_texts: list[str], user_id: str | None = None, **kwargs):
        collection = self.collection(collection_name)
        if user_id:
            kwargs["where"] = self._user_where(user_id)
        results = collection.query(query_texts=query_texts, **kwargs)
        return results

    def collection(self, collection_name: Collection):
        return self.client.get_or_create_collection(name=collection_name.value)

    @staticmethod
    def _metadata(user_id: str | None = None, **kwargs):
        metadata = {key: value for key, value in kwargs.items() if value is not None}
        if user_id:
            metadata["user_id"] = user_id
        return metadata

    @staticmethod
    def _user_where(user_id: str):
        return {"user_id": {"$eq": user_id}}


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
