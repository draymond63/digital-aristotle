# AI Tutor Workflow

This project models a learner as a sparse personal overlay on a global topic graph.
The profile is not the whole memory system. It is a compact frontier map used to guide retrieval, planning, and teaching.

## Core data stores

`Topic graph`

- Canonical topic IDs
- Aliases
- Topic descriptions
- Typed edges such as `prerequisite`, `related`, `part_of`, `application_of`, `enables`

`Profile YAML`

- Durable user topic frontier
- Rough topic ability scores: `intuition`, `details`, `confidence`
- Learning preferences
- Interests
- Current topics

`SQL database`

- Conversation records
- Structured events
- Topic interaction logs
- Profile update history

`Vector database`

- Semantic memories from prior conversations
- User-specific explanations, analogies, misunderstandings, insights, and phrasing

## Example workflow: user asks to learn LC circuits

### 1. Receive user request

User says:

```text
I want to learn LC circuits.
```

System produces:

```text
learning_intent = learn_topic
raw_topic = "LC circuits"
```

AI use:

- AI may classify the request intent if the user message is ambiguous.
- No AI is needed if the request is direct.

### 2. Resolve topic

Inputs:

- Raw user text
- Topic aliases
- Topic graph embeddings
- Existing graph nodes

Process:

```text
"LC circuits" -> lc_circuit
```

AI use:

- Deterministic alias lookup is tried first.
- Embedding similarity can propose candidates.
- AI is used only to resolve ambiguous or messy natural language into canonical topic IDs.

Output:

```text
target_topic = lc_circuit
```

### 3. Load user profile

Input:

```yaml
topics:
  differential_equations:
    intuition: 0.9
    details: 0.8
    confidence: 0.8

  harmonic_oscillator:
    intuition: 0.8
    details: 0.6
    confidence: 0.7

preferences:
  explanation_style:
    - intuition_before_formalism
    - visual
```

Process:

- Load durable user frontier from YAML.
- Do not retrieve detailed memories yet.

AI use:

- No AI. This is deterministic file loading.

Output:

```text
user appears strong in relevant math
user may know oscillator framing
user prefers intuitive/visual explanations
```

### 4. Fetch prerequisite subgraph

Input:

```text
target_topic = lc_circuit
```

Process:

- Traverse the global topic graph.
- Pull required prerequisite neighborhood.

Example prerequisite set:

```text
lc_circuit requires:
- capacitance
- inductance
- voltage_current_charge
- kirchhoffs_voltage_law
- second_order_odes
- sinusoidal_solutions
- harmonic_oscillator
```

AI use:

- No AI during traversal.
- AI may have helped curate or refine the global topic graph offline, but runtime traversal is deterministic.

Output:

```text
required_prereqs = [...]
```

### 5. Overlay explicit user knowledge

Inputs:

- Required prerequisite set
- Profile YAML topic states

Process:

- Match prerequisite topic IDs against profile topic IDs.
- Compute explicit readiness from `intuition`, `details`, and `confidence`.

Example:

```text
explicitly_known:
- harmonic_oscillator

explicitly_strong_related_topic:
- differential_equations

not_explicitly_known:
- capacitance
- inductance
- kirchhoffs_voltage_law
- second_order_odes
- sinusoidal_solutions
```

AI use:

- No AI. This is deterministic comparison and scoring.

Output:

```text
explicit_user_overlay
```

### 6. Infer local readiness

Inputs:

- Explicit user overlay
- Topic graph relations
- Edge weights or transfer rules

Process:

- Infer likely prerequisite readiness from nearby known topics.
- These are planning assumptions, not durable profile facts.

Example:

```text
differential_equations -> second_order_odes, transfer_weight = 0.8
harmonic_oscillator -> lc_circuit_math, transfer_weight = 0.8
```

Temporary output:

```text
assume_known_for_this_lesson:
- second_order_odes
- sinusoidal_solutions
- oscillator_math

do_not_persist_yet
```

AI use:

- Prefer deterministic graph-based inference.
- AI may refine whether an inferred prerequisite is relevant to this specific user request, but AI output should remain temporary unless later confirmed by user evidence.

### 7. Retrieve relevant memories

Inputs:

- Target topic
- Prerequisite topic IDs
- Neighbor topic IDs
- Current topics
- User preferences

Process:

- Query SQL for structured history.
- Query vector DB for semantically relevant prior memories.

Example retrieval query topics:

```text
lc_circuit
harmonic_oscillator
differential_equations
inductance
capacitance
resonance
```

AI use:

- Embeddings are used for vector retrieval.
- AI may summarize retrieved memories into a compact tutor context.
- AI should not invent memories that were not retrieved.

Output:

```text
relevant_memories = [...]
```

### 8. Identify bottlenecks

Inputs:

- Required prerequisites
- Explicit profile overlay
- Local readiness assumptions
- Retrieved memories

Process:

- Classify each prerequisite:

```text
safe_to_assume
likely_known
unknown_low_risk
unknown_high_impact
not_needed_yet
```

Example result:

```text
safe_to_assume:
- second_order_odes
- sinusoidal_solutions
- oscillator_math

needs_intro_or_probe:
- capacitance
- inductance
- voltage_current_charge
```

AI use:

- Deterministic code scores readiness and uncertainty.
- AI may help decide which prerequisites are needed for the requested explanation style, such as intuition-first vs formal derivation.

Output:

```text
bottlenecks = physical meaning of capacitor and inductor
```

### 9. Choose entry point

Inputs:

- Target topic
- Bottlenecks
- User preferences
- Readiness scores

Process:

- Start as high as possible while avoiding unsupported assumptions.
- For a math-strong user, skip basic ODE instruction.
- Focus on the physical mapping.

Output:

```text
entry_point = "LC circuit as a harmonic oscillator: energy moves between capacitor electric field and inductor magnetic field"
```

AI use:

- Deterministic planner can choose candidate entry points.
- AI can refine the phrasing and choose the most natural teaching route from candidates.

### 10. Generate tutor response

Inputs:

- Entry point
- Safe assumptions
- Bottlenecks
- User preferences
- Retrieved memories

AI use:

- AI generates the actual user-facing explanation or diagnostic probe.
- AI must obey the planner context and should not invent profile facts.

Example response:

```text
I’ll assume the oscillator math is familiar and focus on the physical mapping.
An LC circuit is a harmonic oscillator where charge plays the role of position, current plays the role of velocity, capacitor energy is like spring energy, and inductor energy is like kinetic energy.
```

Optional probe:

```text
Do capacitors and inductors already feel intuitive to you, or should we build those two ideas first?
```

### 11. Extract learning updates

Example user response:

```text
Oh, so current is like velocity because it is the derivative of charge.
```

Inputs:

- Recent conversation
- Target topic
- Topic graph
- Current profile

AI use:

- AI extracts possible topic updates, memories, and signals from messy conversation.
- AI output should be structured and validated before persistence.

Example AI-generated update proposal:

```json
{
  "topic_updates": {
    "lc_circuit": {
      "intuition_delta": 0.2,
      "confidence_delta": 0.2
    },
    "current_charge_relationship": {
      "intuition_delta": 0.3
    }
  },
  "memory": "User understood current as derivative of charge in the LC oscillator analogy."
}
```

### 12. Persist durable updates

Inputs:

- AI-generated update proposal
- Validation rules
- Existing profile

Process:

- Clamp score changes.
- Resolve topic IDs.
- Reject unsupported or overly broad claims.
- Persist only durable frontier changes to YAML.
- Store rich evidence in SQL/vector memory.

AI use:

- No AI for final persistence.
- Code validates and applies accepted updates.

Profile YAML update:

```yaml
topics:
  lc_circuit:
    intuition: 0.2
    details: 0.0
    confidence: 0.4
    last_updated: 2026-05-26
```

Memory update:

```text
User understood current as derivative of charge in the LC oscillator analogy.
```

## Principle

Do not eagerly backfill the profile with every inferred prerequisite.

Use inference locally for planning:

```text
This user probably knows enough ODEs to begin LC circuits at the oscillator analogy.
```

Persist only after evidence:

```text
The user demonstrated understanding of current as derivative of charge.
```

The comprehensive user knowledge graph is therefore a computed view:

```text
global topic graph
+ sparse profile YAML
+ SQL/vector memories
+ temporary planning assumptions
```

