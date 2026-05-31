from enum import StrEnum
from hashlib import sha1


class Collection(StrEnum):
    """Name vector collections used by the tutor."""

    INSIGHTS = "insights"
    CONFUSIONS = "confusions"
    PARTIAL_UNDERSTANDINGS = "partial_understandings"
    PREVIOUS_ASKS = "previous_asks"
    SUCCESSFUL_EXPLANATIONS = "successful_explanations"
    LEARNING_PREFERENCES = "learning_preferences"


class MemoryKind(StrEnum):
    """Map extracted memory kinds to vector collections."""

    INSIGHT = "insights"
    CONFUSION = "confusions"
    PARTIAL_UNDERSTANDING = "partial_understandings"
    SUCCESSFUL_EXPLANATION = "successful_explanations"
    LEARNING_PREFERENCE = "learning_preferences"

    @property
    def memory_type(self) -> str:
        """Return the singular prompt-facing memory type."""
        return self.value.removesuffix("s")

    @property
    def collection(self) -> Collection:
        """Return the vector collection for this memory kind."""
        return Collection(self.value)

    @classmethod
    def vector_collections(cls) -> tuple[Collection, ...]:
        """Return all semantic memory vector collections."""
        return tuple(kind.collection for kind in cls)


class SemanticDatabase:
    """Wrap Chroma collections used for semantic retrieval."""

    def __init__(self, path: str = "data/chroma"):
        """Open the persistent Chroma client."""
        from chromadb import PersistentClient

        self.client = PersistentClient(path=path)

    def log_ask(self, msg: str, session_id: int, user_id: str | None = None):
        """Persist a learner question for later similarity search."""
        ask_id = sha1(f"{user_id or ''}:{session_id}:{msg}".encode("utf-8")).hexdigest()[:16]
        self.add(
            collection_name=Collection.PREVIOUS_ASKS,
            ids=[f"{session_id}-{ask_id}"],
            documents=[msg],
            metadatas=[self._metadata(user_id=user_id, session_id=str(session_id))],
        )

    def find_asks(self, query: str, max_dist=0.5, user_id: str | None = None) -> list[str]:
        """Find previous questions similar to a query."""
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
        """Upsert documents into a vector collection."""
        collection = self.collection(collection_name)
        kwargs = {"ids": ids, "documents": documents}
        if metadatas is not None:
            kwargs["metadatas"] = metadatas
        collection.upsert(**kwargs)

    def ids_for_metadata(self, collection_name: Collection, **metadata_filter) -> list[str]:
        """Find vector IDs whose metadata matches all filters."""
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
        """Delete vector rows by ID."""
        if not ids:
            return
        self.collection(collection_name).delete(ids=ids)

    def query_pretty(self, *args, max_dist=0.8, user_id: str | None = None, **kwargs):
        """Query and format deduped results for prompt context."""
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
        """Query one vector collection."""
        collection = self.collection(collection_name)
        if user_id:
            kwargs["where"] = self._user_where(user_id)
        results = collection.query(query_texts=query_texts, **kwargs)
        return results

    def collection(self, collection_name: Collection):
        """Return or create a Chroma collection."""
        return self.client.get_or_create_collection(name=collection_name.value)

    @staticmethod
    def _metadata(user_id: str | None = None, **kwargs):
        """Build Chroma metadata with optional user ID."""
        metadata = {key: value for key, value in kwargs.items() if value is not None}
        if user_id:
            metadata["user_id"] = user_id
        return metadata

    @staticmethod
    def _user_where(user_id: str):
        """Build a Chroma where clause for user filtering."""
        return {"user_id": {"$eq": user_id}}
