from teacher.onboarding.brain import OnboardingBrain
from teacher.onboarding.prompts import PROFILE_EXTRACTION_PROMPT


def test_onboarding_json_tasks_have_room_for_valid_json():
    brain = OnboardingBrain(username="test_onboarding_tasks")
    assert brain.evaluation_task.num_predict >= 300
    assert brain.profile_seed_task.num_predict >= 600


def test_profile_extraction_schema_includes_background_and_short_output_rules():
    assert "background" in PROFILE_EXTRACTION_PROMPT
    assert "starting_point" not in PROFILE_EXTRACTION_PROMPT
    assert "Keep value under 30 words" in PROFILE_EXTRACTION_PROMPT
    assert "Return at most 4 signals" in PROFILE_EXTRACTION_PROMPT


def test_onboarding_is_three_questions_and_handles_uncertain_start():
    brain = OnboardingBrain(username="test_onboarding_tasks")
    assert [dimension for dimension, _ in brain.dimensions_to_cover] == [
        "curiosity_anchor",
        "background",
        "learning_texture",
    ]
    first = "".join(brain.start())
    assert "not sure" in first
    response = "".join(brain.respond("I don't know yet"))
    assert "without picking a topic" in response
    assert "What should I know about your background" in response
    assert brain.current_dimension[0] == "background"
    assert brain.first_curiosity_answer() is None


def test_completed_onboarding_does_not_restart_or_recomplete():
    brain = OnboardingBrain(username="test_onboarding_tasks")
    brain.profile_seed = {"interests": ["open_exploration"]}
    response = "".join(brain.respond("one more thing"))
    assert "You are set up" in response
    assert len(brain.convo.visible_messages()) == 0


def test_first_curiosity_ignores_greetings_and_uncertainty():
    brain = OnboardingBrain(username="test_onboarding_tasks")
    brain.curiosity_answer = "I keep wondering how tiny games work"
    assert brain.first_curiosity_answer() == "I keep wondering how tiny games work"


def test_first_curiosity_does_not_use_background_or_style_answers():
    brain = OnboardingBrain(username="test_onboarding_tasks")
    brain.add_user_message("Hello")
    brain.add_user_message("strong signal processing background")
    brain.add_user_message("visual and intuitive, no long lectures")
    assert brain.first_curiosity_answer() is None


def test_curiosity_detector_rejects_greetings_and_accepts_real_topics():
    assert not OnboardingBrain._looks_like_curiosity("Hello")
    assert not OnboardingBrain._looks_like_curiosity("I don't know yet")
    assert OnboardingBrain._looks_like_curiosity("I keep wondering how tiny games work")


def test_greeting_does_not_consume_curiosity_step():
    brain = OnboardingBrain(username="test_onboarding_tasks")
    list(brain.start())
    response = "".join(brain.respond("Hello"))
    assert "What would you like to explore first?" in response
    assert brain.current_dimension[0] == "curiosity_anchor"
    assert brain.first_curiosity_answer() is None


if __name__ == "__main__":
    test_onboarding_json_tasks_have_room_for_valid_json()
    test_profile_extraction_schema_includes_background_and_short_output_rules()
    test_onboarding_is_three_questions_and_handles_uncertain_start()
    test_completed_onboarding_does_not_restart_or_recomplete()
    test_first_curiosity_ignores_greetings_and_uncertainty()
    test_first_curiosity_does_not_use_background_or_style_answers()
    test_curiosity_detector_rejects_greetings_and_accepts_real_topics()
    test_greeting_does_not_consume_curiosity_step()
    print("onboarding task tests passed")
