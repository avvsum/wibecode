import json

import pytest


USER_TEXT = "Покажи заголовок о Москве. Затем покажи картинку города. Заверши графиком роста."


@pytest.mark.parametrize("retries", [0, 1, 2])
def test_returns_valid_spec_with_at_most_two_retries(api, fake_llm, valid_raw, retries):
    # Valid JSON with an invalid interval also has to trigger correction.
    invalid = '{"duration":3,"scenes":[{"type":"text","text":"x","start":2,"end":1}]}'
    failures = ["{", invalid][:retries]
    messages = []
    for raw in failures:
        with pytest.raises(api.SpecError) as caught:
            api.parse_spec(raw)
        messages.append(str(caught.value))

    generate_spec, requests = fake_llm([*failures, valid_raw])
    result = generate_spec(USER_TEXT)
    assert isinstance(result, str)
    assert json.loads(result) == json.loads(valid_raw)
    assert api.parse_spec(result).duration == 3
    assert len(requests) == retries + 1
    assert requests[0] == [{"role": "user", "content": USER_TEXT}]
    for index, message in enumerate(messages, start=1):
        assert message in requests[index][-1]["content"]


def test_stops_after_initial_attempt_and_two_failed_retries(api, fake_llm, valid_raw):
    invalid = '{"duration":3,"scenes":[{"type":"unknown","start":0,"end":1}]}'
    with pytest.raises(api.SpecError) as validation:
        api.parse_spec(invalid)
    # The fourth response must never be consumed.
    generate_spec, requests = fake_llm([invalid, invalid, invalid, valid_raw])
    with pytest.raises(Exception) as caught:
        generate_spec(USER_TEXT)
    assert len(requests) == 3
    assert str(validation.value) in str(caught.value)
