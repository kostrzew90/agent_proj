# Intel

Oto notatki w formacie markdown, oparte na treści przekazanej przez Ciebie:

---

# Notatki: OpenVino Model Server i Optymizacja AI

## 1. Wstęp
- **OpenVino Model Server** to narzędzie do usługowania modeli AI.
- Umożliwia komunikację między aplikacją a modelem AI poprzez API.
- Obsługuje różne modele: obrazowe, językowe, generatywne, itp.

---

## 2. Obsługa Modeli
- **Obsługiwane modele:**
  - Obrazowe (np. klasyfikacja obrazów)
  - Językowe (np. językowe modelowanie)
  - Generatywne AI
  - Transformacje, itp.

- **Formaty modeli:**
  - PyTorch
  - TensorFlow
  - Keras
  - ONNX
  - Inne

---

## 3. Konwersja Modeli
- Aby użyć modelu w OpenVino, należy go **konwertować** do formatu **DINO**.
- DINO to format wbudowany w OpenVino, umożliwiający optymalizację i uruchamianie na różnych sprzęcie.

---

## 4. Obsługiwane Sprzętowe
- **CPU**
- **Integrowane GPU**
- **Dyskretne GPU (np. Intel Arc)**
- **NPU (np. Intel NPU)**
- **FPGA**

---

## 5. Systemy Operacyjne
- **Windows**
- **Linux**
- **macOS**

---

## 6. OpenVino – Co to jest?
- **OpenVino** to **toolkit** do optymizacji i uruchamiania modeli AI.
- Umożliwia:
  - Optymalizację modeli
  - Uruchamianie na różnych sprzęcie
  - Obsługę różnych typów AI (np. językowe, obrazowe)

---

## 7. OpenVino – Historia
- Został stworzony w 2018 roku jako:
  - **Open Visual Inference**
  - **Neural Network Optimization**
- W 2024 roku:
  - Obsługuje wszystkie rodzaje AI (audio, język, generatywne, itp.)

---

## 8. OpenVino – Licencja
- **Apache 2.0**
- Możliwość użycia w aplikacjach **komercyjnych** i **open source**

---

## 9. OpenVino – Specjalne Pakiety
- **openvino-gen.ai** – specjalny pakiet dla:
  - Generatywnych modeli AI
  - Językowych modeli
  - Pipeline do generacji tekstu
  - Pipeline RAG (Retrieval-Augmented Generation)

---

## 10. Jak Uruchomić OpenVino Model Server?
### Krok 1: Przygotuj model
- Konwertuj model do formatu DINO
- Zapisz jako `.xml` i `.bin`

### Krok 2: Utwórz konfigurację
- Utwórz plik konfiguracyjny (np. `config.json`)
- Wpisz ścieżki do modelu, parametry, itp.

### Krok 3: Uruchom Model Server
- Uruchom OpenVino Model Server
- Przykład:
  ```bash
  openvino-model-server --model /path/to/model --config /path/to/config.json
  ```

### Krok 4: Użyj API
- Wysyłaj żądania do Model Servera
- Otrzymuj odpowiedzi z modelu

---

## 11. Przykład Użycia
### Przykład 1: Klasyfikacja obrazu
- Wysyłasz obraz do API
- Otrzymujesz predykcję: "to banana"

### Przykład 2: Językowy model
- Wysyłasz pytanie: "Co to jest AI?"
- Otrzymujesz odpowiedź: "AI to system..."

### Przykład 3: Stream Mode
- Możliwość otrzymywania odpowiedzi w czasie rzeczywistym

---

## 12. Uwagi
- **Docker** to lepsze środowisko dla OpenVino Model Server niż Windows
- Dla Windows:
  - Obms (OpenVino Model Server) może nie działać idealnie
  - Można użyć **executable obms** z repozytorium

---

## 13. Podsumowanie
- OpenVino to **toolkit** do optymizacji i uruchamiania modeli AI
- OpenVino Model Server to **rozwiązanie do usługowania modeli**
- Obsługuje różne modele, formaty, sprzęty i systemy
- Dostępny pod licencją **Apache 2.0**
- Idealne do zastosowań **komercyjnych** i **open source**

--- 

Jeśli chcesz, mogę przygotować również **dokumentację techniczną**, **przykładowy kod**, lub **szablon konfiguracji**.