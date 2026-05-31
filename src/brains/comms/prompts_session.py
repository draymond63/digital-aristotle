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
- Prefer existing topic IDs from the known graph candidates only when they match the same concept in the same domain.
- If no existing candidate matches the same concept and domain, create a new precise topic_id.
- Do not reuse an existing topic because it shares generic words with the new concept.
- For example, historical state capacity is not the same topic as React state management.
- Do not create plural, adjectival, or reworded variants of an existing topic ID.
- Include evidence for every durable update.
- Return an empty list if the learner did not demonstrate durable understanding.
"""


SESSION_MEMORY_EXTRACTION_PROMPT = """You extract durable semantic memories from an adaptive learning conversation.

Analyze the transcript and return standalone memories only. Do not continue the lesson.

Return strict JSON only:

{
  "confusions": [
    {"topic_id": "canonical_topic_id", "text": "durable unresolved confusion", "confidence": 0.0}
  ],
  "partial_understandings": [
    {"topic_id": "canonical_topic_id", "text": "what the learner partly understands and what remains fuzzy", "confidence": 0.0}
  ],
  "successful_explanations": [
    {"topic_id": "canonical_topic_id", "text": "reusable tutor move that helped", "confidence": 0.0}
  ],
  "learning_preferences": [
    {"topic_id": "canonical_topic_id", "text": "stable tutoring preference", "confidence": 0.0}
  ],
  "insights": [
    {"topic_id": "canonical_topic_id", "text": "durable understanding", "confidence": 0.0}
  ]
}

Rules:
- Prefer fewer high-quality memories over many weak ones.
- Store at most one memory per topic in each bucket.
- Memories must be useful in future tutoring without reading this transcript.
- Do not store long summaries or evidence dumps.
- Do not store a memory for every answered sub-question; save only durable signals that should change future tutoring.
- Do not store generic domain facts that belong in lesson content or the topic graph. Store learner-specific state: what this learner now understands, still misunderstands, responded well to, or prefers.
- If the learner merely follows along, acknowledges, or asks ordinary continuation questions without showing a reusable insight, confusion, preference, or successful explanation pattern, return an empty list.
- First fill "confusions" with durable misconceptions, unresolved confusion, or recurring friction points. If the learner says they are still unclear, confused, struggling, or cannot distinguish concepts by the end, preserve that as confusion instead of rewriting it as insight.
- Then fill "partial_understandings" when the learner has a correct but incomplete mental model: they can state one part, but a boundary, mechanism, or distinction remains fuzzy. Use this instead of emitting both an insight and a confusion for the same topic when the same idea is partly resolved and partly unresolved.
- Then fill "successful_explanations" with reusable tutor moves that helped this learner understand, such as a framing, analogy, contrast, example type, or sequence that led to clarification.
- A successful explanation must name the reusable teaching move. Do not save "explaining X helped" unless the text says what specific move made it work.
- Then fill "learning_preferences" only for stable style or format preferences, not one-off positive reactions.
- Fill "insights" last with durable things the learner now understands. Do not put unresolved or partial understanding here just because the tutor explained it.
- An insight must be grounded in learner evidence: their paraphrase, correction, synthesis, application, or successful boundary-case reasoning. Do not save an insight just because the assistant stated the fact.
- If a learner both understands one distinction and remains confused about another, save one insight and one confusion in their respective buckets.
- Return empty arrays for buckets with nothing durable.
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
- Reject if the proposed topic_id belongs to a different domain or concept than the transcript, even when some words overlap.
- For example, a history discussion of state capacity must not update a React state-management topic.
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
- Prefer existing topic IDs from the known topic graph candidates only when they match the same concept in the same domain.
- If no existing candidate matches the same concept and domain, create a new precise topic_id.
- Do not reuse an existing topic because it shares generic words with the question.
- For example, historical state capacity is not the same topic as React state management.
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
- Return "same_as" only when the new topic is essentially the same concept in the same domain as an existing graph topic.
- Return a typed relation when the new topic is genuinely connected to an existing graph topic.
- Return no connection for unrelated topics, even if both are technical.
- Do not connect topics just because they share generic words.
- For example, historical state capacity is unrelated to React state management unless the transcript explicitly compares those domains.
- Prefer fewer high-confidence connections over broad weak links.
- Confidence must reflect conceptual relatedness, not user interest.
"""
