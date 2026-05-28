# Goal
I want to be able to learn things that I'm curious about by myself. This is an
AI tutor/guide that knows what I already understand so that it can most efficiently
educate me on what I'm curious about. If it understands my frontier of knowledge, it
can also teach me new things that I'm ready to learn but didn't know about.

I've modelled this a graph of topics with different relations between them. The users
"frontier of knowledge" is the collection of all the topics they know about with some
properties to understand their abilities.



https://chatgpt.com/c/6a00ce1f-c71c-83ea-9d8a-86696484883c

# TODO
- Handle different users from telegram
- User evaluation
- Insight/confusion distillation
- Topic edge creation
- Telegram integration
- Saving chats before they are finished


# Flow
## Possible Entrypoints/Tasks
1. Continue off of previous lessons
2. From a question (one off)
  - topic (e.g. Kalman filters)
  - intent? (explain, learn, debug)
  - depth (intuition, math, implementation)
3. Generating new lesson plans/branches from what we know the user is good at (i.e. suggested learning)
4. Generating new lesson plans based on explicit user interest


## Start Lesson
1. User is ready for lesson
2. Planner gets topic to learn
3. From vector DB/memento get related, previously distilled:
   - insights
   - explanations
   - misconceptions
   - interactions
4. From topic DB, get
   - dependency relations (prereqs, subtopics)
   - sources of truth (digested textbooks?)
5. From user DB, get
   - topic confidence/progress
   - learning style preferences (meta-insights)
   - summary of previous lessons

6. Build prompt
```
You are an expert tutor in control theory, signal processing, and applied mathematics.

Your goal is not to lecture, but to adaptively teach a specific student using:
- their current understanding state
- known misconceptions
- prior interactions
- curated source material excerpts

You must teach incrementally, check understanding, and adapt depth dynamically.
```

## During lesson
...

## End Lesson
1. Update user mastery
3. Combine next lesson with user confusion


# Components
- User Vector DB
  - distilled semantic memories
  - insights
  - misconceptions
  - explanation fragments
  - analogies
- SQL
  - chronology
  - model knowledge of topics and their relations
  - mastery history over time (not just current value)
  - lesson outcomes (what improved, what failed)
- yaml
  - distilled state of user skill
  - current lesson plans
  - user preferences

# Model providers

Each AI task specifies its own model. The built-in task model helpers use `USE_API`
in `.env` to choose OpenAI; comment it out to use Ollama. See `ollama.md` for the
current local and OpenAI setup notes.

- Version controlled data with AI controlled git repo

# Telegram

The Telegram interface uses the same `LearningSession` controller as the CLI.

Set these in `.env`:

```
TELEGRAM_KEY=123456:bot-token
TELEGRAM_ALLOWED_IDS=123456789,987654321
```

Run it with:

```
python src/interface/text_chat.py
```

Profiles are stored as `telegram_<telegram_user_id>`. Refused users are appended to
`data/telegram_attempted_usage.jsonl`, which is intentionally ignored by git.
