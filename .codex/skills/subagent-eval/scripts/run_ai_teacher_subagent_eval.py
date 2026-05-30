from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from brains.session import LearningSession


TRACKS = {
    "eval_philosophy": [
        (
            "I understand the basic difference between rationalism and empiricism, but how does Kant's view try to preserve something important from both?",
            "So Kant agrees with empiricists that knowledge starts with experience, but not that it all comes from experience. Is that the key distinction?",
        ),
        (
            "When Kant says the mind contributes structure to experience, how is that different from saying we simply invent reality?",
            "So the mind is not fabricating objects, but setting the conditions under which objects can appear to us as objects?",
        ),
        (
            "How does the analytic/synthetic distinction relate to the idea of synthetic a priori knowledge?",
            "Analytic truths unpack concepts, while synthetic truths add something. So Kant's bold claim is that some ampliative truths are still knowable a priori?",
        ),
        (
            "What would a modern example of a synthetic a priori claim look like, if any still survive after Quine and later philosophy?",
            "Maybe the modern version is weaker: not unrevisable truths, but framework-level commitments we need for inquiry. Is that still Kantian?",
        ),
        (
            "How should I think about the tension between Kantian conditions of possible experience and contemporary cognitive science?",
            "Would the best reconciliation be that Kant explains normatively what experience requires, while cognitive science explains causally how creatures like us implement it?",
        ),
    ],
    "eval_statistics": [
        (
            "I'm comfortable with mean, variance, and distributions. Can you explain standard error as a property of an estimator rather than just 'standard deviation divided by root n'?",
            "So the standard error belongs to the estimator's sampling behavior, not to the observed sample itself?",
        ),
        (
            "How does the sampling distribution connect the population parameter, the estimator, and a confidence interval?",
            "When we say 95% confidence, the probability is about the procedure capturing the fixed parameter over repeated samples, right?",
        ),
        (
            "What exactly changes when we move from a z-interval to a t-interval?",
            "Is the key issue that we replaced the known population variance with an estimated sample variance?",
        ),
        (
            "Why is a p-value not the probability that the null hypothesis is true, and what probability statement is it actually making?",
            "So the p-value assumes the null is true and asks how surprising the data, or more extreme data, would be under that assumption?",
        ),
        (
            "How would I compare frequentist confidence intervals with Bayesian credible intervals without reducing it to slogans?",
            "For confidence intervals, the parameter is fixed and the interval is random; for credible intervals, the parameter is treated probabilistically conditional on the model. Is that precise enough?",
        ),
    ],
    "eval_machine_learning": [
        (
            "I understand supervised learning at a high level. Can you explain empirical risk minimization and why loss functions matter?",
            "So ERM is basically choosing the hypothesis that minimizes average loss on the training sample, as a proxy for true population risk?",
        ),
        (
            "How should I think about bias-variance tradeoff in relation to underfitting and overfitting?",
            "So high bias means the model class is too limited to capture the real pattern, while high variance means it's too sensitive to the particular sample?",
        ),
        (
            "What role does regularization play, and why can constraining a model improve generalization?",
            "Is regularization best understood as reducing variance, encoding prior assumptions, or changing the effective hypothesis space?",
        ),
        (
            "How do embeddings turn discrete symbolic inputs into something a neural network can optimize over?",
            "Are embeddings learned because the model adjusts vector positions to make downstream prediction easier?",
        ),
        (
            "How does representation learning in deep networks differ from hand-engineered feature extraction?",
            "Is the key difference that representation learning makes the feature extraction itself part of the optimization process?",
        ),
    ],
    "eval_web_architecture": [
        (
            "I know HTML, CSS, JavaScript, and basic React. Can you explain why state management becomes difficult as an app grows?",
            "So the hard part is not just where do I store the value, but keeping multiple parts of the UI consistent when the same fact matters in different places?",
        ),
        (
            "How should I distinguish local component state, derived state, server state, and URL state?",
            "Would a filter dropdown be local state if it only affects one panel, but URL state if I want the filtered view to be shareable or reloadable?",
        ),
        (
            "What makes React's rendering model different from directly mutating the DOM?",
            "So instead of saying change this DOM node, I describe what the UI should look like for the current state, and React figures out the updates?",
        ),
        (
            "How do optimistic updates work, and where do they become risky?",
            "If I mark a habit complete before the server confirms it, I need a rollback path if the request fails, right?",
        ),
        (
            "If I were building a collaborative habit tracker, how should I think about components, data ownership, synchronization, and persistence?",
            "Would the habit definition, membership, and completion records be separate entities rather than one big nested object?",
        ),
    ],
    "eval_history": [
        (
            "I know the basic timeline of the French Revolution. How do historians distinguish structural causes from triggering events?",
            "So structural causes set the range of instability, while triggering events explain why rupture happened at that particular moment?",
        ),
        (
            "How should I weigh economic pressures, Enlightenment ideas, and institutional breakdown without treating one as the single real cause?",
            "Is the better move to ask what each factor made possible, rather than ranking them as if only one was the true cause?",
        ),
        (
            "What does it mean to analyze the Revolution through social class, political culture, or state-capacity frameworks?",
            "So each framework highlights a different causal mechanism: material interests, shared meanings, or administrative limits?",
        ),
        (
            "How do primary sources from elite political actors distort our understanding of popular participation?",
            "Would popular action appear mainly when elites found it threatening or politically useful enough to record?",
        ),
        (
            "How would a revisionist interpretation of the French Revolution differ from a Marxist or liberal interpretation?",
            "Is revisionism pushing back against class-driven necessity by emphasizing contingency, political language, and institutional conflict?",
        ),
    ],
}


def run_track(user_id: str, turns: list[tuple[str, str]]) -> dict:
    session = LearningSession(user_id=user_id)
    interactions = []
    for index, (question, follow_up) in enumerate(turns, start=1):
        first = session.ask(question)
        second = session.ask(follow_up)
        interactions.append(
            {
                "index": index,
                "question": question,
                "first_response": first,
                "follow_up": follow_up,
                "second_response": second,
            }
        )
    report = session.finalize()
    return {
        "user_id": user_id,
        "interactions": interactions,
        "finalization": {
            "summary": report.summary,
            "next_step": report.next_step,
            "conversation_path": report.conversation_path,
            "profile_backup_path": report.profile_backup_path,
            "audit_id": report.audit_id,
            "memories_saved": report.memories_saved,
            "topics_updated": report.topics_updated,
            "topic_update_notes": report.topic_update_notes,
            "graph_changes": report.graph_changes,
        },
        "profile": session.profile.to_dict(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run configurable ai-teacher subagent evaluations.")
    parser.add_argument(
        "--agents",
        type=int,
        default=5,
        help="Number of default tracks to run. Ignored when --tracks is provided.",
    )
    parser.add_argument(
        "--tracks",
        help="Comma-separated track/user IDs to run, for example eval_philosophy,eval_statistics.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/evals",
        help="Directory for the JSON result artifact.",
    )
    parser.add_argument(
        "--name",
        default="multi-agent-knowledge",
        help="Filename prefix for the JSON result artifact.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Print the selected tracks and questions without running model calls or writing results.",
    )
    return parser.parse_args()


def selected_tracks(args: argparse.Namespace) -> list[str]:
    if args.tracks:
        track_names = [item.strip() for item in args.tracks.split(",") if item.strip()]
    else:
        if args.agents < 1:
            raise ValueError("--agents must be at least 1")
        track_names = list(TRACKS)[: args.agents]
    unknown = [track_name for track_name in track_names if track_name not in TRACKS]
    if unknown:
        raise ValueError(f"Unknown tracks: {unknown}. Available tracks: {list(TRACKS)}")
    if not args.tracks and len(track_names) < args.agents:
        raise ValueError(f"Requested {args.agents} agents but only {len(TRACKS)} tracks are available")
    return track_names


def main() -> None:
    args = parse_args()
    track_names = selected_tracks(args)
    if args.preview:
        for track_name in track_names:
            print(f"# {track_name}")
            for index, (question, follow_up) in enumerate(TRACKS[track_name], start=1):
                print(f"{index}. question: {question}")
                print(f"   follow_up: {follow_up}")
            print()
        return

    timestamp = datetime.now().isoformat(timespec="seconds").replace(":", "-")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{args.name}-{timestamp}.json"

    results = []
    for track_name in track_names:
        print(f"running {track_name}", flush=True)
        results.append(run_track(track_name, TRACKS[track_name]))

    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"output={output_path}")


if __name__ == "__main__":
    main()
