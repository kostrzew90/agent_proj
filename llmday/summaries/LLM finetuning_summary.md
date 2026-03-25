# Streszczenie: LLM finetuning

**Streszczenie wykładu: Ataki typu Poisoning na modele AI**

Wykład poświęcony został zagrożeniom bezpieczeństwa w systemach AI, z koncentracją na atakach typu *Poisoning*. Głównym tematem było wprowadzanie szkodliwych danych do zbioru treningowego, aby wpłynąć na zachowanie modelu i uzyskać nieprawidłowe odpowiedzi.

**Kluczowe tezy i wnioski:**
- *Poisoning* to atak, w którym atakujący wprowadza szkodliwe dane do zbioru treningowego, co może prowadzić do nieprawidłowego zachowania modelu, np. zwracania szkodliwych odpowiedzi, przekazywania danych osobowych lub wykonywania działań szkodliwych.
- Ataki mogą być realizowane w czasie treningu (wprowadzanie danych szkodliwych do zbioru) lub w czasie inferencji (wprowadzanie szkodliwych wzorców do wejścia modelu).
- *Trigger* to specjalny wzorzec, który atakujący wprowadza do danych treningowych, aby model uczył się, że po jego wystąpieniu należy wykonać określoną akcję, np. zwrócić szkodliwą odpowiedź.

**Najważniejsze insights i praktyczne wskazówki:**
- Aby chronić modele przed atakami *Poisoning*, należy stosować weryfikację danych treningowych, kontrolę dostępu do zbioru, użycie modeli z wyższą odpornością (np. z mechanizmem wykrywania *triggerów*), monitorowanie zachowania modelu oraz czyszczenie danych (data sanitization).
- Praktyczne przykłady pokazują, jak ataki mogą wpływać na systemy AI w medycynie, finansach i edukacji, a także jak można je neutralizować poprzez odpowiednie środki ochrony.

**Technologie, narzędzia i firmy:**
- W wykładzie nie zostały wymienione konkretne firmy ani narzędzia, jednak podkreślano potrzebę stosowania zaawansowanych metod bezpieczeństwa AI, takich jak systemy monitorowania zachowania modelu, mechanizmy wykrywania *triggerów*, oraz techniki czyszczenia danych.

**Podsumowanie:**
Ataki typu *Poisoning* stanowią poważne zagrożenie dla systemów AI, które mogą prowadzić do nieprawidłowego zachowania modeli. Ochrona przed nimi wymaga kompleksowego podejścia, obejmującego weryfikację danych, kontrolę dostępu, wyższą odporność modeli oraz ciągłe monitorowanie ich zachowania. Wartość wykładu polegała na zwróceniu uwagi na konieczność rozwoju technologii bezpieczeństwa AI, aby zapobiec atakom i zabezpieczyć systemy przed nieprawidłowym zachowaniem.