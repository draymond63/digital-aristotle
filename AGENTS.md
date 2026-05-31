# Project Context

This is an exploratory AI tutor/guide. It helps a user learn things they are curious about by tracking their knowledge frontier and adapting explanations.

## Core model

- `topic graph`: canonical topics plus prerequisite/related edges.
- `profile YAML`: small durable overlay on the topic graph, not a memory database.
- `SQL/vector DB`: rich conversation evidence, prior explanations, misconceptions, analogies, and semantic memories.
- `computed user knowledge graph`: topic graph + profile + retrieved memories + temporary planning assumptions.

## Profile rules

- Store compact durable state only: `background`, `topics`, `preferences`, `interests`, `current_topics`.
- Topic state uses `intuition`, `details`, `confidence`, `last_updated`.
- Normalize profile identifiers to lowercase snake case and dedupe.
- Do not store evidence, summaries, or long notes in YAML; use SQL/vector memory.
- Background is an informal prior, not proof of topic mastery.

## AI usage

- Use deterministic code for graph traversal, profile loading/saving, readiness scoring, and persistence.
- Use AI for messy language: topic resolution, onboarding profile seed generation, memory/update extraction, and user-facing teaching.
- AI-generated profile updates must be compact and validated before persistence.

## Editing

- Use ~/.virtualenvs/teacher/ as the venv
- Never attempt to preserve old functionality if its design is incompatible
- Always delete uselss code, but let the user know
- Preferred cleaner, less-developed features over bloated ones. This is an experimental repo and I'm the only contributor
- If things don't work, don't add try-catch's or if statements - solve the problem or let the user know you can't
