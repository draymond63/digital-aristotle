from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

from teacher.persistence.sql import SQLDatabase


DB_PATH = ROOT / "data" / "aristotle.db"
BACKUP_DIR = ROOT / "data" / "db_backups"


def main() -> None:
    """Back up and clean topic graph rows."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = BACKUP_DIR / f"aristotle-before-graph-cleanup-{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)

    db = SQLDatabase(DB_PATH)
    merges = [
        ("Electromagnetism", "electromagnetism"),
        ("attention_mechanisms", "attention_mechanism"),
        ("kalman_filter_controls", "kalman_filter"),
        ("control_systems_state_estimation", "state_estimation"),
    ]
    merged = sum(1 for source, target in merges if db.merge_topics(source, target))

    db.cursor.execute("DELETE FROM topic_edges WHERE topic1 = topic2")
    self_edges_deleted = db.cursor.rowcount

    db.cursor.execute(
        """
        DELETE FROM topic_edges
        WHERE topic1 = 'vector_addition'
          AND topic2 = 'attention_mechanism'
          AND relation_type = 'prerequisite'
        """
    )
    weak_edges_deleted = db.cursor.rowcount
    db.cursor.execute(
        """
        DELETE FROM topic_edges
        WHERE topic1 = 'vector_similarity_dot_product'
          AND topic2 = 'attention_mechanism'
          AND relation_type = 'application_of'
        """
    )
    duplicate_edges_deleted = db.cursor.rowcount

    curated_edges = [
        (
            "vector_similarity_dot_product",
            "attention_mechanism",
            "prerequisite",
            0.8,
            "Attention uses vector similarity scores to decide which values to blend.",
        ),
        (
            "topology_continuous_deformation",
            "topology_homeomorphism",
            "prerequisite",
            0.7,
            "Homeomorphism formalizes sameness under continuous deformation.",
        ),
        (
            "topology_holes_connectivity",
            "topology_homeomorphism",
            "related",
            0.65,
            "Both are introductory topology ideas used before algebraic topology.",
        ),
        (
            "state_estimation",
            "kalman_filter",
            "prerequisite",
            0.75,
            "Kalman filters are a concrete method for recursive state estimation.",
        ),
    ]
    added = 0
    for topic1, topic2, relation, confidence, evidence in curated_edges:
        if db.upsert_topic_edge(topic1, topic2, relation, confidence=confidence, evidence=evidence):
            added += 1

    readable_names = {
        "spectral_sequences_algebraic_topology": "Spectral Sequences In Algebraic Topology",
        "topology_continuous_deformation": "Continuous Deformation",
        "topology_holes_connectivity": "Holes And Connectivity",
        "topology_homeomorphism": "Homeomorphism",
        "vector_similarity_dot_product": "Vector Similarity And Dot Product",
    }
    for topic_id, name in readable_names.items():
        db.cursor.execute("UPDATE topics SET name = ? WHERE id = ?", (name, topic_id))
    db.cursor.execute("UPDATE topics SET aliases_json = '[]' WHERE aliases_json IS NULL OR aliases_json = '{}'")

    db.conn.commit()
    db.close()

    print(f"backup={backup_path}")
    print(f"merged_topics={merged}")
    print(f"self_edges_deleted={self_edges_deleted}")
    print(f"weak_edges_deleted={weak_edges_deleted}")
    print(f"duplicate_edges_deleted={duplicate_edges_deleted}")
    print(f"curated_edges_upserted={added}")


if __name__ == "__main__":
    main()
