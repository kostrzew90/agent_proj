import json

from pydantic import BaseModel, Field, ValidationError

PROMPT_TEXT = """Jestes parserem posilkow. Otrzymasz opis posilku po polsku.
Zwroc WYLACZNIE JSON (bez markdown, bez dodatkowego tekstu) w formacie:
{{"kcal": number, "protein_g": number, "fat_g": number, "carbs_g": number,
  "opis": string, "confidence": number 0..1, "when_hint": string or null}}
when_hint: null (teraz), "Nh_ago" (np. "3h_ago"), "yesterday", albo "yesterday_evening".
Jesli opis NIE dotyczy jedzenia, zwroc WYLACZNIE {{"error": "not_food"}}.

Opis posilku: {text}
"""

PROMPT_PHOTO = """Jestes parserem posilkow. Na zdjeciu jest posilek.
Zwroc WYLACZNIE JSON w formacie:
{"kcal": number, "protein_g": number, "fat_g": number, "carbs_g": number,
  "opis": string, "confidence": number 0..1, "when_hint": null}
Jesli na zdjeciu NIE ma jedzenia, zwroc WYLACZNIE {"error": "not_food"}.
"""


class ParsedMeal(BaseModel):
    kcal: float = Field(gt=0)
    protein_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    carbs_g: float = Field(ge=0)
    opis: str
    confidence: float = Field(ge=0, le=1)
    when_hint: str | None = None


class NotFoodError(Exception):
    pass


class ParseError(Exception):
    pass


class TransientLLMError(Exception):
    pass


class GeminiClient:
    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash", model=None):
        self.model_name = model_name
        if model is not None:
            self._model = model
        else:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self._model = genai.GenerativeModel(model_name)

    def parse_text(self, text: str) -> ParsedMeal:
        try:
            response = self._model.generate_content(PROMPT_TEXT.format(text=text))
        except Exception as exc:
            raise TransientLLMError(str(exc)) from exc
        return self._parse_response(response.text)

    def parse_photo(self, image_path: str) -> ParsedMeal:
        import PIL.Image
        image = PIL.Image.open(image_path)
        try:
            response = self._model.generate_content([PROMPT_PHOTO, image])
        except Exception as exc:
            raise TransientLLMError(str(exc)) from exc
        return self._parse_response(response.text)

    def _parse_response(self, raw_text: str) -> ParsedMeal:
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ParseError(f"nieparsowalny JSON: {exc}") from exc

        if data.get("error") == "not_food":
            raise NotFoodError()

        try:
            return ParsedMeal.model_validate(data)
        except ValidationError as exc:
            raise ParseError(f"nieprawidlowy schemat: {exc}") from exc
