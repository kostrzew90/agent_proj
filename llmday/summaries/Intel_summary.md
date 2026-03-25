# Streszczenie: Intel

**Streszczenie wykładu: OpenVino Model Server i Optymizacja AI**

Wykład poświęcony został narzędziu **OpenVino Model Server**, które umożliwia usługowanie modeli sztucznej inteligencji (AI) w różnych aplikacjach. Głównym celem prezentacji było przedstawienie możliwości i zalet tego narzędzia, a także omówienie procesu konwersji modeli, ich uruchamiania oraz integracji z aplikacjami.

**Kluczowe tezy i wnioski:**
- OpenVino to **toolkit** do optymalizacji i uruchamiania modeli AI, który obsługuje różne typy modeli, w tym obrazowe, językowe i generatywne.
- OpenVino Model Server to **rozwiązanie do usługowania modeli AI**, umożliwiające komunikację między aplikacją a modelem poprzez API.
- Narzędzie obsługuje wiele formatów modeli, takich jak PyTorch, TensorFlow, Keras, ONNX oraz inne, które można konwertować do formatu **DINO** – specjalnego formatu wbudowanego w OpenVino.
- Obsługuje różne typy sprzętu, w tym CPU, GPU (integrowane i dyskretne), NPU oraz FPGA.
- Dostępne są zarówno wersje dla systemów Windows, Linux oraz macOS.

**Najważniejsze insights i praktyczne wskazówki:**
- Aby uruchomić OpenVino Model Server, należy najpierw przekonwertować model do formatu DINO i przygotować plik konfiguracyjny.
- Warto zwrócić uwagę na środowisko uruchomieniowe – **Docker** jest lepszym wyborem niż Windows, gdzie mogą wystąpić problemy z kompatybilnością.
- Można wykorzystać specjalny pakiet **openvino-gen.ai**, który wspiera generatywne modele AI, modele językowe oraz pipeline RAG (Retrieval-Augmented Generation).
- OpenVino Model Server umożliwia również **stream mode**, co pozwala otrzymywać odpowiedzi w czasie rzeczywistym.

**Technologie, narzędzia i firmy:**
- **OpenVino** – narzędzie do optymalizacji i uruchamiania modeli AI.
- **OpenVino Model Server** – usługa do usługowania modeli AI.
- **DINO** – format modeli wbudowany w OpenVino.
- **PyTorch, TensorFlow, Keras, ONNX** – formaty modeli obsługiwane przez OpenVino.
- **Docker** – środowisko uruchomieniowe zalecane do działania OpenVino Model Server.
- **Intel** – firma producenta sprzętu wspierającego OpenVino (np. NPU, GPU, FPGA).

Wykład podkreślał, że OpenVino jest doskonałym wyborem zarówno dla zastosowań **komercyjnych**, jak i **open source**, dzięki swojej elastyczności, wydajności i szerokiej kompatybilności.