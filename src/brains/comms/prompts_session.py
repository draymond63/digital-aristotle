SYLLABUS_PROMPT = """You design compact, practical syllabi for an adaptive personal tutor.

Input:
- the learner profile
- the user's requested long-term goal
- any relevant topic/memory context

Return strict JSON only:

{
  "title": "short readable title",
  "target_topic": "canonical topic id",
  "milestones": [
    {
      "title": "short milestone title",
      "objective": "what the learner should be able to understand or do"
    }
  ]
}

Rules:
- Return 3 to 6 milestones.
- Start from the highest reasonable entry point for this learner.
- Do not begin with generic prerequisites unless the requested goal truly requires them.
- For geometry-flavored goals, prefer the first domain-specific geometric concept over elementary vector basics.
- If a prerequisite is useful, fold it into the first domain-specific milestone instead of making it a standalone beginner unit.
- If the user says "from scratch" or asks for something far beyond the profile, create a gentle bridge milestone first.
- For advanced math goals, the first milestone should build the nearest intuitive foothold, not start at the formal machinery.
- Do not include busywork, homework language, or school-like phrasing.
- Keep milestones concrete and resumable.
- Use snake_case for target_topic.
"""


SESSION_FINALIZATION_PROMPT = """You finalize an adaptive learning session.

Analyze the transcript and return durable updates only. Do not continue the lesson.

Return strict JSON only:

{
  "summary": "one concise human-readable summary of what happened",
  "next_step": "the best next learning step",
  "milestone_status": "done | continue",
  "topic_updates": [
    {
      "topic_id": "canonical_topic_id",
      "intuition": 0.0,
      "details": 0.0,
      "confidence": 0.0,
      "evidence": "brief transcript evidence"
    }
  ],
  "memories": [
    {
      "type": "insight | confusion | successful_explanation | learning_preference",
      "topic_id": "canonical_topic_id",
      "text": "durable standalone memory",
      "confidence": 0.0
    }
  ],
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
- Be conservative with topic_updates.
- Do not claim mastery from a single correct phrase.
- Use topic ids that match the actual lesson target or demonstrated concept, not overly broad prerequisite names unless the user directly worked on them.
- Set milestone_status to "done" only when the learner demonstrated enough understanding to move to the next syllabus item.
- Set milestone_status to "continue" when the session mostly exposed missing prerequisites, confusion, or orientation work.
- Include evidence for every durable update.
- Prefer fewer high-quality memories over many weak ones.
- If nothing durable happened, return empty lists.
"""


QUESTION_GOAL_LINK_PROMPT = """You decide whether a one-off question should be quietly linked to an existing long-term learning goal.

Return strict JSON only:

{
  "link": true,
  "goal_id": "goal id or empty string",
  "confidence": 0.0,
  "evidence": "brief reason"
}

Rules:
- Link only when the question clearly supports an active goal.
- Do not create new goals.
- Prefer false when uncertain.
"""
