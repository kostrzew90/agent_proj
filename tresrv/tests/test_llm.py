import pytest

from tresrv.llm import GeminiClient, ParsedMeal, NotFoodError, ParseError


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeModel:
    def __init__(self, response_text):
        self._response_text = response_text
        self.last_call_args = None

    def generate_content(self, *args, **kwargs):
        self.last_call_args = (args, kwargs)
        return FakeResponse(self._response_text)


def test_parse_text_valid_response():
    fake = FakeModel(
        '{"kcal": 450, "protein_g": 30, "fat_g": 15, "carbs_g": 40, '
        '"opis": "kurczak z ryżem", "confidence": 0.85, "when_hint": null}'
    )
    client = GeminiClient(api_key="unused", model=fake)

    result = client.parse_text("kurczak z ryżem")

    assert isinstance(result, ParsedMeal)
    assert result.kcal == 450
    assert result.confidence == 0.85
    assert result.when_hint is None


def test_parse_text_not_food_raises():
    fake = FakeModel('{"error": "not_food"}')
    client = GeminiClient(api_key="unused", model=fake)

    with pytest.raises(NotFoodError):
        client.parse_text("stół z drewna")


def test_parse_text_garbage_json_raises_parse_error():
    fake = FakeModel("to nie jest JSON")
    client = GeminiClient(api_key="unused", model=fake)

    with pytest.raises(ParseError):
        client.parse_text("cokolwiek")


def test_parse_text_missing_required_field_raises_parse_error():
    fake = FakeModel('{"kcal": 450, "protein_g": 30}')
    client = GeminiClient(api_key="unused", model=fake)

    with pytest.raises(ParseError):
        client.parse_text("cokolwiek")


def test_parse_text_confidence_out_of_range_raises_parse_error():
    fake = FakeModel(
        '{"kcal": 450, "protein_g": 30, "fat_g": 15, "carbs_g": 40, '
        '"opis": "x", "confidence": 1.5, "when_hint": null}'
    )
    client = GeminiClient(api_key="unused", model=fake)

    with pytest.raises(ParseError):
        client.parse_text("cokolwiek")
