# LiteLLM — bramka LLM (VPS Contabo)

Jeden adres dla wszystkich modeli: Mac Studio (Ollama) → Gemini → OpenRouter free.
Przełączanie przy błędach/429, ślady w LangFuse (projekt „LITE LLM ARGUS”), metryki w Prometheusie (`mac-prometheus`, job `litellm`).

- Adres: `http://100.71.197.18:4000` (tylko Tailscale). Klucz: `LITELLM_MASTER_KEY` z `~/litellm/.env` na VPS.
- Grupy i kolejność: patrz nagłówek `config.yaml`.
- Format: OpenAI (`/v1/chat/completions`).

## Przykłady

Tekst:
```bash
curl -s http://100.71.197.18:4000/v1/chat/completions -H "Authorization: Bearer $K" -H "Content-Type: application/json" \
  -d '{"model":"rag-chat","messages":[{"role":"user","content":"Czym jest faktura VAT?"}]}'
```

OCR / opis obrazu (skan, zdjęcie telefonem) — grupa `ocr`:
```python
import base64, json, urllib.request
img = base64.b64encode(open("paragon.jpg", "rb").read()).decode()
body = {"model": "ocr", "temperature": 0, "messages": [{"role": "user", "content": [
    {"type": "text", "text": "Przepisz dokładnie cały tekst z obrazu, linia po linii. Zwróć tylko tekst."},
    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + img}}]}]}
req = urllib.request.Request("http://100.71.197.18:4000/v1/chat/completions", json.dumps(body).encode(),
                             {"Authorization": "Bearer " + K, "Content-Type": "application/json"})
print(json.load(urllib.request.urlopen(req))["choices"][0]["message"]["content"])
```
Opis zamiast OCR: zmień tekst polecenia, np. „Opisz po polsku, co przedstawia to zdjęcie”.

Myślenie modeli z Maca jest domyślnie wyłączone; włączenie dla pojedynczego zapytania: `"think": true`.

## Który model odpowiedział
Nagłówki odpowiedzi: `x-litellm-model-api-base` (100.79.154.116 = Mac, generativelanguage = Gemini, openrouter.ai = OpenRouter), `x-litellm-attempted-fallbacks`.

## Wdrożenie
Z commita: `git archive <commit> litellm | ssh root@169.58.146.162 'cd ~ && tar x'`, potem `cd ~/litellm && docker compose restart litellm`.
Sekrety w `~/litellm/.env` (poza gitem): `LITELLM_MASTER_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `TAILSCALE_IP`.

## Pułapki
- LiteLLM nie wstrzymuje modelu, który jest jedynym w swojej grupie — dlatego kolejność (`order`) w jednej grupie zamiast `fallbacks` między grupami.
- W grupie najwyżej jeden model z Maca: drugi przy wyłączonym Macu dołożyłby kolejne 45 s czekania.
- LiteLLM ma częste zgłoszenia bezpieczeństwa — sprawdzaj https://github.com/BerriAI/litellm/security/advisories i aktualizuj przypiętą wersję obrazu.
