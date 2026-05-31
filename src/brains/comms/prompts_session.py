SESSION_SUMMARY_PROMPT = """You summarize an adaptive learning conversation.

Analyze the transcript. Do not continue the lesson.

Return strict JSON only:

{
  "summary": "one concise human-readable summary of what happened",
  "next_step": "the best next learning step"
}

Rules:
- Focus on what the learner clarified or struggled with.
- Keep both fields concise.
- Do not include profile updates, memories, or graph updates.
"""


SESSION_TOPIC_UPDATES_PROMPT = """You extract learner profile topic updates from an adaptive learning conversation.

Analyze the transcript and return compact durable profile updates only. Do not continue the lesson.

Input:
- the visible session transcript
- known global topic graph candidates as system context

Return strict JSON only:

{
  "topic_updates": [
    {
      "topic_id": "canonical_topic_id",
      "intuition": 0.0,
      "details": 0.0,
      "confidence": 0.0,
      "evidence": "brief transcript evidence"
    }
  ]
}

Rules:
- Be conservative.
- Do not claim mastery from a single correct phrase.
- Use topic ids that match the actual question or demonstrated concept, not overly broad prerequisite names unless the user directly worked on them.
- Prefer existing topic IDs from the known graph candidates when they fit.
- Do not create plural, adjectival, or reworded variants of an existing topic ID.
- Include evidence for every durable update.
- Return an empty list if the learner did not demonstrate durable understanding.
"""


SESSION_MEMORY_EXTRACTION_PROMPT = """You extract durable semantic memories from an adaptive learning conversation.

Analyze the transcript and return standalone memories only. Do not continue the lesson.

Return strict JSON only:

{
  "memories": [
    {
      "type": "insight | confusion | successful_explanation | learning_preference",
      "topic_id": "canonical_topic_id",
      "text": "durable standalone memory",
      "confidence": 0.0
    }
  ]
}

Rules:
- Prefer fewer high-quality memories over many weak ones.
- Memories must be useful in future tutoring without reading this transcript.
- Do not store long summaries or evidence dumps.
- Use "insight" for durable things the learner now understands.
- Use "confusion" for durable misconceptions, unresolved confusion, or recurring friction points.
- Use "successful_explanation" for reusable tutor moves that helped this learner understand, such as a framing, analogy, contrast, example type, or sequence that led to clarification.
- Use "learning_preference" only for stable style or format preferences, not one-off positive reactions.
- Do not classify every clarified concept as a successful_explanation. That type is about the teaching tactic, not the learner's knowledge.
- Return an empty list if nothing durable should be saved.
"""


SESSION_GRAPH_UPDATES_PROMPT = """You extract global topic graph updates from an adaptive learning conversation.

Analyze the transcript and return topic graph updates only. Do not continue the lesson.

Input:
- the visible session transcript
- known global topic graph candidates as system context

Return strict JSON only:

{
  "graph_updates": {
    "topics": [
      {
        "topic_id": "canonical_topic_id",
        "name": "Readable Name",
        "description": "short description",
        "confidence": 0.0,
        "evidence": "brief transcript evidence"
      }
    ],
    "edges": [
      {
        "topic1": "canonical_topic_id",
        "topic2": "canonical_topic_id",
        "relation_type": "prerequisite | related | part_of | application_of | enables",
        "confidence": 0.0,
        "evidence": "brief transcript evidence"
      }
    ]
  }
}

Rules:
- Be conservative.
- Return at most 3 topics and at most 3 edges.
- Do not create a graph node for every concept mentioned.
- Prefer topics that are durable curriculum nodes, not one-off examples or broad umbrella terms.
- Prefer existing topic IDs from the known graph candidates when they fit.
- Do not create plural, adjectival, or reworded variants of an existing topic ID.
- Prefer empty lists over verbose graph expansion.
- Include evidence for every durable update.
- Use empty strings for unknown optional text. Do not return null values.
- Use lowercase snake_case topic IDs.
- Relation types must be one of: prerequisite, related, part_of, application_of, enables.
- Return empty topic and edge lists if nothing durable should be added.
"""


PROFILE_UPDATE_GATE_PROMPT = """You decide whether a proposed learner profile topic update is supported by the session transcript.

Input:
- the visible session transcript
- one proposed topic update as JSON
- the current learner profile as system context

Return strict JSON only:

{
  "accept": true,
  "reason": "brief reason grounded in transcript evidence"
}

Rules:
- Accept only when the learner demonstrated understanding, useful intuition, or a stable preference/background signal for the proposed topic.
- Reject updates based only on the tutor explaining something, the learner asking a question, or the learner explicitly saying they are confused.
- Do not require special wording in the evidence field. Judge the transcript directly.
- Be conservative with mastery, but do not reject a valid small update because the evidence sentence uses different phrasing.
- The proposed topic_id must match the concept actually discussed or demonstrated.
- Return false when the transcript does not support the proposed intuition/details/confidence levels.
"""


QUESTION_TOPIC_RESOLUTION_PROMPT = """You resolve a learner's current question into compact technical topic IDs.

Input:
- the current user question
- the learner profile and known topic graph candidates as system context

Return strict JSON only:

{
  "topics": [
    {
      "topic_id": "canonical_topic_id",
      "name": "Readable Topic Name",
      "description": "short description of the concept in this question",
      "confidence": 0.0
    }
  ]
}

Rules:
- Return 1 to 3 topics.
- Prefer existing topic IDs from the known topic graph candidates when they fit.
- If the question uses indirect wording, infer the technical topic it points at.
- Use lowercase snake_case topic IDs.
- Do not include generic helper topics like "question" or "learning".
- Confidence should reflect whether this is a valid technical topic from the user's question, not whether it already exists in the graph.
"""


TOPIC_GRAPH_CONNECTION_PROMPT = """You decide how a new/resolved topic connects to existing global topic graph nodes.

Input:
- one new/resolved topic
- candidate existing graph topics as system context

Return strict JSON only:

{
  "connections": [
    {
      "topic_id": "existing_topic_id",
      "relation_type": "same_as | prerequisite | related | part_of | application_of | enables | none",
      "confidence": 0.0,
      "evidence": "brief reason"
    }
  ]
}

Rules:
- Use only existing topic_id values from the candidate list.
- Return "same_as" when the new topic is essentially the same concept as an existing graph topic.
- Return a typed relation when the new topic is genuinely connected to an existing graph topic.
- Return no connection for unrelated topics, even if both are technical.
- Prefer fewer high-confidence connections over broad weak links.
- Confidence must reflect conceptual relatedness, not user interest.
"""
