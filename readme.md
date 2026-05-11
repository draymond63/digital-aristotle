https://chatgpt.com/c/6a00ce1f-c71c-83ea-9d8a-86696484883c

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

- Version controlled data with AI controlled git repo