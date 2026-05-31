---
name: subagent-eval
description: Run configurable multi-agent or multi-user evaluation sequences for ai-teacher. Use when the user asks to retry the subagents, spawn N test agents, run progressive question tracks, compare learner-specific persisted knowledge, inspect the topic graph/vector DB after agent runs, or build/adjust reusable agent-eval scenarios.
---

# Subagent Eval

## Workflow

Use this skill to run ai-teacher knowledge-persistence evaluations with a configurable number of simulated learner agents.

1. Confirm the requested agent count, track names, or subject mix from the user request.
2. Preview the exact generated question/follow-up sequence before running anything:

```powershell
$env:PYTHONPATH='src'
& $HOME\.virtualenvs\teacher\Scripts\python.exe .codex\skills\subagent-eval\scripts\run_ai_teacher_subagent_eval.py --agents 5 --preview
```

Use `--scenario extension` when continuing from the previous five eval learners with related but different questions:

```powershell
$env:PYTHONPATH='src'
& $HOME\.virtualenvs\teacher\Scripts\python.exe .codex\skills\subagent-eval\scripts\run_ai_teacher_subagent_eval.py --agents 5 --scenario extension --preview
```

3. Show the preview to the user and wait for approval or edits.
4. After approval, run the repo-local wrapper script without `--preview`:

```powershell
$env:PYTHONPATH='src'
& $HOME\.virtualenvs\teacher\Scripts\python.exe .codex\skills\subagent-eval\scripts\run_ai_teacher_subagent_eval.py --agents 5
```

5. Use `--tracks` when the user names specific tracks:

```powershell
$env:PYTHONPATH='src'
& $HOME\.virtualenvs\teacher\Scripts\python.exe .codex\skills\subagent-eval\scripts\run_ai_teacher_subagent_eval.py --tracks eval_philosophy,eval_statistics --preview
```

6. After the run, inspect the output JSON, SQL topic graph/profile data, and Chroma collections:

```powershell
$env:PYTHONPATH='src'
& $HOME\.virtualenvs\teacher\Scripts\python.exe .codex\skills\subagent-eval\scripts\inspect_ai_teacher_subagent_eval.py
```

## Rules

- Treat each track as a separate learner identity; do not reuse one `user_id` for multiple simulated learners.
- Preserve progressive multi-message interaction: every topic step should include an initial question and at least one follow-up that builds on the answer.
- Always show the planned questions before running the test. Do not start model calls or mutate persistence until the user approves the preview.
- If the user asks for "subagents" in this repo, interpret that as the ai-teacher simulated learner tracks unless they explicitly ask for Codex worker agents.
- For live model runs, use the user's requested model/provider setup. If network/API access fails because of sandboxing, request escalation.
- Summarize persistence quality, not just conversation quality: profile topics, SQL graph nodes/edges, vector memories, duplicate/stale data, and whether profile IDs match graph IDs.
- Do not silently ignore failed finalization, JSON truncation, or empty persistence. Surface the failure and inspect logs/artifacts.

## Adjusting Scenarios

The wrapper owns the default `TRACKS` and `run_track` implementation. To change the default questions or add more agents, edit `.codex/skills/subagent-eval/scripts/run_ai_teacher_subagent_eval.py`.

Use a larger `--agents` value than the available default tracks only after adding more tracks to the utility. The script fails loudly when the count cannot be satisfied. Use `SCENARIOS` to add separate scenario sets such as continuation tracks.

The inspector defaults to the newest `data/evals/multi-agent-knowledge-*.json` artifact. Use `--eval-path` to inspect a specific artifact and `--users` to inspect a subset of persisted users.
