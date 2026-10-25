"""Offline tests for YouTube metadata: parsing, limits and generate_metadata retries."""

import json

import pytest

from src.llm import FakeLLMClient, MetadataError, SpecGenerationError, VideoMetadata, generate_metadata
from src.llm.metadata import TITLE_MAX, parse_metadata, tags_length
from src.llm.prompt import EXAMPLE_METADATA, EXAMPLE_SPEC, METADATA_PROMPT

USER_TEXT = 'Ролик про рост продаж: заголовок, потом график.\n\nrender_mode: "2d"'


def payload(**changes):
    data = {
        "title": "Продажи выросли втрое",
        "description": "Итоги года за 15 секунд.\n\n#Shorts #бизнес",
        "tags": ["рост продаж", "итоги года", "бизнес"],
    }
    data.update(changes)
    return json.dumps(data, ensure_ascii=False)


def test_example_is_valid_and_prompt_states_the_format():
    meta = parse_metadata(EXAMPLE_METADATA)
    assert meta.title and meta.tags and "#Shorts" in meta.description
    for text in ('"title"', '"description"', '"tags"', "#Shorts", "ТОЛЬКО", str(TITLE_MAX)):
        assert text in METADATA_PROMPT


def test_tags_are_cleaned_and_shorts_hashtag_is_added():
    meta = parse_metadata(
        payload(description="Итоги года.", tags=["#Бизнес", " итоги   года ", "бизнес", ""])
    )
    assert meta.tags == ("Бизнес", "итоги года")
    assert meta.description == "Итоги года.\n\n#Shorts"


def test_existing_shorts_hashtag_is_kept_once():
    meta = parse_metadata(payload(description="Итоги.\n\n#shorts #бизнес"))
    assert meta.description.lower().count("#shorts") == 1


@pytest.mark.parametrize(
    "raw, field",
    [
        ("не json", "невалидный JSON"),
        ("[]", "объектом"),
        (payload(title=""), "title"),
        (payload(title="x" * (TITLE_MAX + 1)), "title"),
        (payload(description=None), "description"),
        (payload(description="Смотри <тут>"), "description"),
        (payload(tags="бизнес"), "tags"),
        (payload(tags=["#"]), "tags"),
        (payload(tags=["a <b>"]), "tags"),
        (payload(tags=[f"тег {i:03}" for i in range(60)]), "tags"),
    ],
)
def test_invalid_metadata_names_the_problem(raw, field):
    with pytest.raises(MetadataError, match=field):
        parse_metadata(raw)


def test_tags_length_counts_like_youtube():
    assert tags_length(["a", "b c"]) == 7  # 1 + "b c" in quotes (5) + one comma
    assert tags_length([]) == 0


def test_as_text_lists_all_fields():
    meta = VideoMetadata("Название", "Описание\n\n#Shorts", ("a", "b c"))
    assert meta.as_text() == (
        "Название:\nНазвание\n\nОписание:\nОписание\n\n#Shorts\n\nТеги:\na, b c"
    )


def test_request_has_description_and_spec_without_mode_hint():
    fake = FakeLLMClient([payload()])
    meta = generate_metadata(USER_TEXT, EXAMPLE_SPEC, client=fake)

    assert meta.title == "Продажи выросли втрое"
    assert len(fake.calls) == 1
    (request,) = fake.calls[0]
    assert "Ролик про рост продаж: заголовок, потом график." in request["content"]
    assert EXAMPLE_SPEC in request["content"]
    assert "render_mode" not in request["content"]


def test_invalid_replies_get_fix_ups_with_the_error():
    too_long = payload(title="x" * (TITLE_MAX + 1))
    fake = FakeLLMClient(["Вот метаданные!", too_long, f"```json\n{payload()}\n```"])
    meta = generate_metadata(USER_TEXT, EXAMPLE_SPEC, client=fake)

    assert meta.tags == ("рост продаж", "итоги года", "бизнес")
    assert len(fake.calls) == 3
    assert "невалидный JSON" in fake.calls[1][-1]["content"]
    assert f"title: {TITLE_MAX + 1} символов" in fake.calls[2][-1]["content"]


def test_gives_up_after_two_retries():
    fake = FakeLLMClient(["{", "{", payload(tags=[]), payload()])
    with pytest.raises(SpecGenerationError, match="tags"):
        generate_metadata(USER_TEXT, EXAMPLE_SPEC, client=fake)
    assert len(fake.calls) == 3  # the fourth reply is never requested
