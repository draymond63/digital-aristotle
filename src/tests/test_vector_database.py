from brains.data.db_vector import Collection, SemanticDatabase


class FakeCollection:
    def __init__(self):
        self.upserts = []
        self.queries = []

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return {"documents": [["remember this"]], "distances": [[0.1]]}


class MultiQueryCollection(FakeCollection):
    def query(self, **kwargs):
        self.queries.append(kwargs)
        return {
            "documents": [
                ["missed because first query is distant"],
                ["remember this", "duplicate"],
                ["remember this", "better match"],
            ],
            "distances": [
                [1.2],
                [0.4, 0.7],
                [0.2, 0.1],
            ],
        }


class FakeClient:
    def __init__(self):
        self.collections = {}

    def get_or_create_collection(self, name):
        if name not in self.collections:
            self.collections[name] = FakeCollection()
        return self.collections[name]


def make_db():
    db = SemanticDatabase.__new__(SemanticDatabase)
    db.client = FakeClient()
    return db


def test_log_ask_stores_user_metadata():
    db = make_db()
    db.log_ask("what is covariance?", session_id=123, user_id="tester")
    collection = db.collection(Collection.PREVIOUS_ASKS)
    assert collection.upserts[0]["ids"] == ["123"]
    assert collection.upserts[0]["metadatas"] == [{"user_id": "tester"}]


def test_query_filters_by_user_id():
    db = make_db()
    text = db.query_pretty(
        collection_name=Collection.INSIGHTS,
        query_texts=["covariance"],
        user_id="tester",
    )
    collection = db.collection(Collection.INSIGHTS)
    assert "remember this" in text
    assert collection.queries[0]["where"] == {"user_id": {"$eq": "tester"}}


def test_query_pretty_flattens_multiple_query_results():
    db = make_db()
    db.client.collections[Collection.INSIGHTS.value] = MultiQueryCollection()
    text = db.query_pretty(
        collection_name=Collection.INSIGHTS,
        query_texts=["indirect wording", "profile topic"],
        user_id="tester",
    )
    assert "better match" in text
    assert "remember this" in text
    assert "missed because first query is distant" not in text
    assert text.index("better match") < text.index("remember this")


if __name__ == "__main__":
    test_log_ask_stores_user_metadata()
    test_query_filters_by_user_id()
    test_query_pretty_flattens_multiple_query_results()
    print("vector database tests passed")
