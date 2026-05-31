from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from brains.comms.agent_base import Agent, Conversation, Task, get_control_model
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


EXTENSION_TRACKS = {
    "eval_philosophy": [
        (
            "Last time we framed Kant's conditions of possible experience as normative rather than causal. How would that help explain why causality is not just a habit of association for Kant?",
            "So Kant is saying causality is a rule that experience must conform to in order to count as objective experience, not a pattern we merely notice after repeated observations?",
        ),
        (
            "How does Kant's view of space and time as forms of intuition fit with the idea that the mind structures experience without inventing objects?",
            "Would it be fair to say space and time are not properties we discover in things-in-themselves, but the framework through which appearances become ordered for us?",
        ),
        (
            "Where does Kant's answer to Hume succeed or fail if modern science revises our concepts of space, time, and causality?",
            "Maybe Kant's stronger claim fails if the exact framework is revisable, but the weaker idea survives: experience requires some organizing framework before evidence can be interpreted?",
        ),
        (
            "How should I distinguish Kant's transcendental argument from an empirical psychological explanation?",
            "So a transcendental argument asks what must already be presupposed for experience or judgment to be possible, while psychology asks how a mind actually produces those judgments?",
        ),
        (
            "If Quine undermines a sharp analytic/synthetic boundary, what happens to Kant's synthetic a priori project?",
            "Does Quine force us to replace fixed a priori truths with a web of commitments that are more central or less central, but still revisable?",
        ),
    ],
    "eval_statistics": [
        (
            "Last time we separated estimator variability from sample variability. How does that distinction show up in bootstrap confidence intervals?",
            "So the bootstrap approximates the estimator's sampling behavior by resampling from the observed data, rather than directly measuring the population's variability?",
        ),
        (
            "How should I think about confidence interval coverage when the model assumptions are wrong?",
            "Is the guarantee only about the procedure under its assumptions, so bad assumptions can make the nominal 95% coverage misleading?",
        ),
        (
            "What's the difference between statistical significance and practical significance in the p-value framework?",
            "So a tiny p-value can happen for a small, practically irrelevant effect if the sample size is huge enough?",
        ),
        (
            "How does multiple testing change the interpretation of p-values?",
            "If I run many tests, even true nulls can produce some small p-values by chance, so I need to control the family-wise error rate or false discovery rate?",
        ),
        (
            "Can you connect Bayesian credible intervals to priors without making priors sound like arbitrary opinion?",
            "Would a good prior be better understood as explicit modeling information that can be weak, strong, skeptical, or based on previous data?",
        ),
    ],
    "eval_machine_learning": [
        (
            "Last time ERM was minimizing training loss as a proxy for true risk. How does validation data help estimate whether that proxy is working?",
            "So validation loss is not used to fit the parameters directly, but to estimate generalization and compare choices like model class or regularization strength?",
        ),
        (
            "How do regularization and early stopping compare as ways of controlling effective model complexity?",
            "Is early stopping a kind of implicit regularization because it limits how far optimization can fit idiosyncrasies in the training data?",
        ),
        (
            "What does it mean for embeddings to encode similarity, and when can that similarity be misleading?",
            "So nearby vectors mean the model found similar usefulness for the training objective, not necessarily human-interpretable semantic sameness in every context?",
        ),
        (
            "How does representation learning relate to transfer learning?",
            "Is transfer learning useful because earlier training has already shaped representations that can be reused or fine-tuned for a related task?",
        ),
        (
            "Where does the bias-variance story break down for very large overparameterized neural networks?",
            "So double descent suggests that after interpolation, larger models can sometimes generalize better again, which complicates the simple U-shaped bias-variance picture?",
        ),
    ],
    "eval_web_architecture": [
        (
            "Last time we separated local, URL, server, and derived state. How would that affect where I put caching logic in a React app?",
            "So server-state libraries are mostly about cache ownership, freshness, background refetching, and mutation coordination rather than just global state storage?",
        ),
        (
            "How should I think about optimistic updates when multiple clients can edit the same habit record?",
            "If two clients update at the same time, rollback is not enough; I also need conflict resolution or a server-side ordering rule, right?",
        ),
        (
            "What makes normalized data models easier to synchronize than one big nested object?",
            "So separate entities let updates touch smaller records, avoid duplicating facts, and make conflict handling more local?",
        ),
        (
            "How do React component boundaries relate to data ownership in a collaborative app?",
            "Would components ideally subscribe to the smallest stable slice of shared data they need, instead of receiving a giant app object through props?",
        ),
        (
            "How should URL state and permissions interact in a collaborative habit tracker?",
            "So the URL can identify the current view or selected team, but authorization still has to be enforced by the server rather than trusted from the client route?",
        ),
    ],
    "eval_history": [
        (
            "Last time we used the lens of structural causes versus triggering events. How would that apply specifically to the Estates-General and the Tennis Court Oath?",
            "So the fiscal crisis and representation disputes created structural pressure, while the Tennis Court Oath marks a triggering political rupture in sovereignty?",
        ),
        (
            "How would a state-capacity framework explain the monarchy's failure differently from a class-conflict framework?",
            "So state capacity focuses less on bourgeois versus aristocratic interest and more on the crown's inability to tax, administer, and legitimate reform?",
        ),
        (
            "How can political culture explain why symbolic acts and language mattered so much during the Revolution?",
            "Would political culture make us look at legitimacy, honor, citizenship, and sovereignty as forces that shaped what actions seemed possible?",
        ),
        (
            "How should I evaluate popular violence without treating it as either irrational mob action or pure revolutionary virtue?",
            "So the better move is to ask what information, fears, institutions, and political opportunities made violence seem meaningful or strategic to participants?",
        ),
        (
            "How do revisionist interpretations handle the Reign of Terror compared with Marxist interpretations?",
            "Would revisionists emphasize contingency, wartime emergency, factional politics, and language of virtue, while Marxists tie Terror more directly to class struggle and defense of revolution?",
        ),
    ],
}


STRUGGLE_TRACKS = {
    "eval_philosophy": [
        (
            "I can repeat that Kant thinks causality is a condition for objective experience, but I still don't see why that is not just a fancy psychological claim about how humans happen to think.",
            None,
        ),
        (
            "I get the words 'transcendental argument,' but I keep losing the difference between proving a condition of experience and making an empirical generalization.",
            None,
        ),
        (
            "Quine makes the analytic/synthetic boundary look unstable. If that boundary collapses, I don't understand what exactly is left of synthetic a priori knowledge.",
            None,
        ),
        (
            "If modern physics revises space, time, and causality, why shouldn't that just refute Kant's claim that these are necessary structures of experience?",
            None,
        ),
        (
            "I struggle to tell whether Kant is making a claim about reality, about our concepts, or about the rules of inquiry. How do I separate those without oversimplifying him?",
            None,
        ),
    ],
    "eval_statistics": [
        (
            "I understand the formula for standard error, but I still confuse the estimator's sampling distribution with the distribution of individual observations.",
            None,
        ),
        (
            "Confidence interval coverage makes sense in repeated sampling, but I don't know how to reason about one interval after I've already observed my data.",
            None,
        ),
        (
            "I can say a p-value is not P(null is true), but when I try to explain what probability it actually is, I keep slipping back into that mistake.",
            None,
        ),
        (
            "Multiple testing corrections feel like a technical patch. I don't understand the deeper reason many valid tests create misleading evidence when viewed together.",
            None,
        ),
        (
            "Bayesian credible intervals feel more intuitive than confidence intervals, but I struggle to explain what role the prior is playing without making it sound arbitrary.",
            None,
        ),
    ],
    "eval_machine_learning": [
        (
            "I understand ERM as minimizing training loss, but I don't really see why low training loss can be a bad sign instead of simply evidence that the model learned well.",
            None,
        ),
        (
            "Bias and variance make sense in simple curves, but I struggle to apply the idea to large neural networks where bigger models can generalize better.",
            None,
        ),
        (
            "I know regularization can improve generalization, but I don't understand whether it is reducing variance, adding prior assumptions, changing optimization, or all of those.",
            None,
        ),
        (
            "Embeddings are described as encoding similarity, but I get confused about whose notion of similarity they encode and why that can fail.",
            None,
        ),
        (
            "Transfer learning sounds like reusing representations, but I don't understand when the reused representation helps versus when it carries the wrong bias into the new task.",
            None,
        ),
    ],
    "eval_web_architecture": [
        (
            "I understand local, URL, derived, and server state as categories, but I still struggle to decide where a real piece of state belongs when it affects several components.",
            None,
        ),
        (
            "Optimistic updates seem straightforward until multiple clients edit the same data. I don't understand how rollback, conflict resolution, and server ordering fit together.",
            None,
        ),
        (
            "Normalized data models sound cleaner, but I struggle to see why one nested object is actually dangerous in a collaborative app.",
            None,
        ),
        (
            "React component boundaries and data ownership blur together for me. I don't know when a component should own state versus subscribe to shared state.",
            None,
        ),
        (
            "I get that permissions must be enforced server-side, but I struggle with how URL state, client routing, and authorization checks should work together.",
            None,
        ),
    ],
    "eval_history": [
        (
            "I understand structural causes versus triggers in the abstract, but I struggle to apply that distinction to the Estates-General without making the trigger sound like the real cause.",
            None,
        ),
        (
            "State capacity and class conflict both seem plausible explanations for the French Revolution, and I don't know how to compare them without just picking a favorite lens.",
            None,
        ),
        (
            "Political culture explanations feel vague to me. I don't understand how language, legitimacy, and symbols can be causal rather than just descriptive.",
            None,
        ),
        (
            "Popular violence during the Revolution is hard for me to analyze without moralizing it or treating crowds as irrational. What framework avoids both mistakes?",
            None,
        ),
        (
            "Revisionist accounts of the Terror confuse me because I can't tell whether they are denying social causes or just rejecting a deterministic class-conflict story.",
            None,
        ),
    ],
}


STRUGGLE_OUTCOMES = {
    "eval_philosophy": "unresolved_by_end",
    "eval_statistics": "understands_by_end",
    "eval_machine_learning": "partial_understanding_by_end",
    "eval_web_architecture": "unresolved_by_end",
    "eval_history": "understands_by_end",
}


SCENARIOS = {
    "base": TRACKS,
    "extension": EXTENSION_TRACKS,
    "struggle": STRUGGLE_TRACKS,
}


FOLLOW_UP_PROMPT = """You are simulating an advanced learner testing an AI tutor.

Write the learner's next message after reading the tutor answer.

Rules:
- Ask exactly one follow-up question.
- The question must build directly on the tutor's actual answer.
- Preserve the learner's confusion instead of pretending the answer solved it.
- Be specific about what is still unclear.
- Do not answer the question yourself.
- Keep it to 1-2 sentences.
"""


def struggle_trajectory_instruction(user_id: str, turn_index: int, total_turns: int) -> str:
    outcome = STRUGGLE_OUTCOMES.get(user_id, "partial_understanding_by_end")
    late_turn = turn_index >= total_turns - 1
    if outcome == "understands_by_end":
        if late_turn:
            return (
                "Trajectory: this learner is starting to understand. The follow-up should synthesize "
                "the key distinction in their own words and ask for a precise check or boundary case."
            )
        return (
            "Trajectory: this learner is struggling productively. The follow-up should identify a concrete "
            "remaining confusion while using part of the tutor answer correctly."
        )
    if outcome == "unresolved_by_end":
        return (
            "Trajectory: this learner remains confused by the end of the session. The follow-up should show "
            "that the answer did not resolve the core confusion, while still engaging with a specific part of it."
        )
    if late_turn:
        return (
            "Trajectory: this learner reaches only partial understanding. The follow-up should correctly state "
            "one piece but leave a deeper unresolved distinction explicit."
        )
    return (
        "Trajectory: this learner is struggling. The follow-up should be specific, confused, and connected "
        "to the tutor answer."
    )


def generate_follow_up(
    agent: Agent,
    user_id: str,
    question: str,
    answer: str,
    turn_index: int,
    total_turns: int,
) -> str:
    task = Task(
        "simulated_struggling_follow_up",
        FOLLOW_UP_PROMPT,
        model=get_control_model(),
        temperature=0.55,
        num_predict=180,
    )
    conversation = Conversation()
    conversation.append_user(
        f"Simulated learner track: {user_id}\n\n"
        f"{struggle_trajectory_instruction(user_id, turn_index, total_turns)}\n\n"
        f"Original question:\n{question}\n\n"
        f"Tutor answer:\n{answer}"
    )
    follow_up = agent.run_task(task, conversation).strip()
    if not follow_up:
        raise RuntimeError(f"Generated empty follow-up for {user_id}: {question!r}")
    return follow_up


def run_track(user_id: str, turns: list[tuple[str, str | None]]) -> dict:
    session = LearningSession(user_id=user_id)
    simulator = Agent()
    interactions = []
    total_turns = len(turns)
    for index, (question, planned_follow_up) in enumerate(turns, start=1):
        first = session.ask(question)
        follow_up = planned_follow_up
        follow_up_generated = False
        if follow_up is None:
            follow_up = generate_follow_up(simulator, user_id, question, first, index, total_turns)
            follow_up_generated = True
        second = session.ask(follow_up)
        interactions.append(
            {
                "index": index,
                "question": question,
                "first_response": first,
                "follow_up": follow_up,
                "follow_up_generated": follow_up_generated,
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
        "--scenario",
        choices=sorted(SCENARIOS),
        default="base",
        help="Question scenario set to use.",
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
    tracks = SCENARIOS[args.scenario]
    if args.tracks:
        track_names = [item.strip() for item in args.tracks.split(",") if item.strip()]
    else:
        if args.agents < 1:
            raise ValueError("--agents must be at least 1")
        track_names = list(tracks)[: args.agents]
    unknown = [track_name for track_name in track_names if track_name not in tracks]
    if unknown:
        raise ValueError(f"Unknown tracks: {unknown}. Available tracks: {list(tracks)}")
    if not args.tracks and len(track_names) < args.agents:
        raise ValueError(f"Requested {args.agents} agents but only {len(tracks)} tracks are available")
    return track_names


def main() -> None:
    args = parse_args()
    tracks = SCENARIOS[args.scenario]
    track_names = selected_tracks(args)
    if args.preview:
        for track_name in track_names:
            print(f"# {track_name}")
            if args.scenario == "struggle":
                print(f"outcome: {STRUGGLE_OUTCOMES.get(track_name, 'partial_understanding_by_end')}")
            for index, (question, follow_up) in enumerate(tracks[track_name], start=1):
                print(f"{index}. question: {question}")
                if follow_up is None:
                    print("   follow_up: generated live from the tutor answer by the struggling learner simulator")
                else:
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
        results.append(run_track(track_name, tracks[track_name]))

    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"output={output_path}")


if __name__ == "__main__":
    main()
