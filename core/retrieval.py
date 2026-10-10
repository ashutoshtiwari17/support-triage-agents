"""Vector search over the policy chunks in Firestore.

The audience filter is applied inside the Firestore query, before the similarity
search, so chunks the person may not see are never read, let alone sent to the model.
The audience comes from the employee record on the server, never from the model.
"""
import os

from google import genai
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from google.cloud.firestore_v1.vector import Vector
from google.genai import types

from core.schemas import EmploymentType

COLLECTION = "policy_chunks"               # must match scripts/ingest.py and the index
DIMENSIONS = 768                           # must match the index
AUDIENCE_FLAG = {
    EmploymentType.EMPLOYEE: "for_employee",
    EmploymentType.CONTRACTOR: "for_contractor",
}

_db: firestore.Client | None = None


def db() -> firestore.Client:
    """One Firestore client per process, created on first use."""
    global _db
    if _db is None:
        _db = firestore.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    return _db


def embed_query(client: genai.Client, text: str) -> list[float]:
    result = client.models.embed_content(
        model=os.environ["EMBED_MODEL"],
        contents=text,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY", output_dimensionality=DIMENSIONS),
    )
    return result.embeddings[0].values


def search_chunks(client: genai.Client, query: str, audience: EmploymentType, k: int = 8) -> list[dict]:
    """The k chunks closest in meaning to the query, among those this audience may see."""
    flag = AUDIENCE_FLAG[EmploymentType(audience)]       # KeyError for anything unexpected
    vector_query = (
        db().collection(COLLECTION)
        .where(filter=FieldFilter(flag, "==", True))
        .find_nearest(
            vector_field="embedding",
            query_vector=Vector(embed_query(client, query)),
            distance_measure=DistanceMeasure.COSINE,
            limit=k,
            distance_result_field="distance",
        )
    )
    results = []
    for doc in vector_query.get():
        d = doc.to_dict()
        results.append({
            "policy_id": d["policy_id"],
            "section": f"{d['section']}. {d['heading']}",
            "text": d["content"].split("\n", 1)[-1],
            "source": f"{d['source']}, page {d['page']}",
            "distance": round(d["distance"], 3),
        })
    return results
