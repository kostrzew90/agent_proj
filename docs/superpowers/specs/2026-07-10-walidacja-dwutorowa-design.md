# Walidacja dwutorowa: asystent skrzynki + strażnik terminów

**Data:** 2026-07-10
**Status:** Zaakceptowany
**Projekty:** nowe — walidacja produktu

## Cel

Za ~3 miesiące (do połowy października 2026) mieć dane zamiast hipotez do decyzji: który wertykał "dokument → akcja" staje się produktem SaaS na drodze do pełnego etatu użytkownika. Po drodze: pierwszy przychód z wdrożeń.

Teza strategiczna: największy potencjał nie tkwi w AI samym w sobie, tylko we wzorcu dokument → decyzja → akcja (mail, PDF, faktura, wezwanie, decyzja administracyjna, pismo sądowe, umowa, reklamacja). AI jest silnikiem; produktem jest automatyzacja pracy z dokumentami, nie kolejny chatbot.

Oba tory prowadzone są roboczo jako "Concierge AI" — usługa wspomagana AI, nie SaaS. Produkt wyłania się dopiero, gdy okaże się, że ok. 5 klientów potrzebuje dokładnie tego samego.

## Kontekst decyzji

Przegląd portfolio (RAG, Argus, VINhunter, Hermes, Selfmadeagent, trading-app) wykazał: silna inżynieria, brak klientów — technologia szukająca rynku. Dwa realne sygnały popytu:

1. 1–2 znajomych przedsiębiorców prosi o system czytający maile (wp.pl/gmail), tworzący zbiorczą listę w skoroszycie, przygotowujący odpowiedzi i szablon faktury.
2. Dostęp do kancelarii adwokackiej (klient Artur Borzewski) — branża dokumentochłonna, wrażliwa na RODO, z bólem terminów procesowych.

Odrzucone kierunki:
- Sprzedaż sygnałów krypto z Argusa (rynek spalonego zaufania, za mało danych n=5, ryzyko KNF).
- Ocena stanu aut po zdjęciach (słaby sygnał, odpowiedzialność).
- "Więcej agentów na VPS do jakichś zadań" (myślenie od technologii do rynku).

## Tor 1 — Asystent skrzynki dla znajomych (gotówka + nauka domeny)

### Gate zero

Przed napisaniem choćby linijki kodu: rozmowa z każdym z 2 znajomych — potwierdzenie, że płacą (propozycja: 1,5–3 tys. zł setup + 100–200 zł/mc utrzymanie; kwota dostosowana do relacji) i spisanie ich konkretnego procesu: jakie maile, co ma być w skoroszycie, jak wygląda ich faktura. Jeśli żaden nie chce zapłacić — tor umiera i to też jest wynik walidacji (sygnał był pozorny), zostaje sam Tor 2.

### Zakres techniczny (celowo minimalny)

- Odczyt skrzynki: Gmail API + wp.pl przez IMAP.
- Orkiestracja: istniejący n8n w Dockerze — zero nowej infrastruktury.
- LLM klasyfikuje/streszcza mail → wiersz w Google Sheets (data, nadawca, temat, streszczenie, kategoria, status).
- Szkic odpowiedzi + wypełniony szablon faktury jako propozycja do akceptacji — klient zatwierdza, nic nie wysyła się samo.
- Hosting: Oracle VPS (działa 24/7, obok Argusa); LLM przez API (Gemini/Groq — za zgodą klienta na przetwarzanie maili); lokalny model odpada (laptop nie chodzi 24/7, VPS bez GPU).

### Poza zakresem Toru 1

Własny frontend, multi-tenant, KSeF, automatyczne wysyłanie czegokolwiek. To wdrożenie, nie produkt — produktowe wnioski wyciągamy z użycia.

### Kryterium sukcesu

Po 4 tygodniach od wdrożenia: minimum 30 przetworzonych maili tygodniowo, minimum 5 wygenerowanych faktur, klient zagląda do systemu minimum 3 dni w tygodniu, opłacony drugi miesiąc abonamentu. Progi są wartościami domyślnymi — kalibrowane przy gate zero do realnego wolumenu klienta (firma z 10 mailami/tydz. dostaje proporcjonalnie niższy próg). Miernik pomocniczy: czy sami proszą o więcej / polecają dalej.

## Tor 2 — Strażnik terminów dla kancelarii (produkt)

### Krok 1 — discovery z Borzewskim (bez kodu)

Godzinna rozmowa wg scenariusza: jak wpływa korespondencja (e-Doręczenia / papier / skan), kto i jak wylicza terminy, gdzie jest kalendarz kancelarii, historia "prawie przegapionego" terminu, czy zapłaciłby i ile. Wynik spisany. Jeśli discovery pokaże, że problem jest u niego marginalny — pytamy 2–3 inne kancelarie (polecenia od niego), zanim porzucimy kierunek.

Zasada prowadzenia rozmowy: nie pytać "czy to byłoby przydatne?" — zamiast tego "pokaż mi ostatnie pismo", potem "co robisz dalej?" i obserwować. Obserwacja realnego procesu ujawnia problemy, których klient sam nie nazywa.

### Krok 2 — MVP tylko jeśli discovery potwierdzi ból

- Wejście: PDF/skan pisma (upload lub folder), na start bez integracji z e-Doręczeniami.
- Ekstrakcja: typ pisma, data doręczenia, termin (LLM + reguły; docelowo terminy liczone wg KPC, w MVP data wyciągnięta z pisma).
- Wyjście: propozycja wpisu do kalendarza (Google Calendar / ICS) zawsze z akceptacją człowieka — system jest drugą parą oczu, nigdy autopilotem; każda ekstrakcja pokazuje fragment pisma, z którego wzięła datę.
- Deal: Borzewski używa za darmo/symbolicznie jako design partner w zamian za cotygodniowy feedback i zgodę na referencję.

### Kryterium sukcesu

Kancelaria po miesiącu wprowadza pisma sama, bez przypominania, i potwierdza "nie chcę tego oddać". To sygnał do budowy SaaS.

## Metryki od pierwszego dnia

Tor 1: liczba maili, ile AI sklasyfikowało poprawnie, ile odpowiedzi zaakceptowano bez zmian, ile poprawiono, czas wykonania.

Tor 2: liczba pism, ile terminów AI znalazło, ile poprawił człowiek, ile minut zajęło przetworzenie.

Uzasadnienie: to przyszły materiał marketingowy — "AI poprawnie wyciągnęło termin w 94% z 430 dokumentów" jest mocniejszym argumentem niż "wykorzystujemy AI".

### Log błędów

Każdy przypadek pomyłki AI zapisywany — nie po to, żeby karać model, tylko żeby wiedzieć czego nie umie, co poprawić, które przypadki obsłużyć regułami. Za pół roku taki zbiór to przewaga konkurencyjna.

### Gate: pytanie po 2 tygodniach

Niezależnie od 4-/12-tygodniowych kryteriów sukcesu: ~2 tygodnie po starcie wdrożenia (w obu torach) zadać klientowi pytanie "Gdybym jutro wyłączył ten system, czego najbardziej by Ci brakowało?" — NIE "czy Ci się podoba?" (prowadzi do uprzejmych odpowiedzi). Odpowiedź wskazuje realną wartość, wcześnie i tanio.

## Bramka decyzyjna (~połowa października 2026)

Porównanie torów po faktach: retencja, kto sam wraca i prosi o więcej, kto poleca, realna skłonność do płacenia. Zwycięski wertykał dostaje pełne zaangażowanie; brainstorming produktu SaaS dopiero gdy powtarzalność potwierdzona u kolejnych klientów (patrz Concierge AI w sekcji Cel).

Możliwe uczciwe wyniki:
- Oba słabe — szukamy dalej, taniej o 3 miesiące błędu.
- Oba żywe — wybieramy wyższy sufit cenowy (prawdopodobnie kancelarie).

## Poza zakresem całości

- Argus: zero prac rozwojowych, zbiera dane na VPS (dojrzewanie 30d), powrót osobno.
- Motoryzacja: zaparkowana świadomie (asystent zakupu auta możliwy w przyszłości — dane twarde VIN + typowe usterki, nie zdjęcia).
- Sprzedaż zimna do obcych firm: w fazie walidacji tylko ciepłe kontakty.
- Rejestracja działalności / formalności: odnotowane, poza tym designem (przy pierwszej fakturze — działalność nierejestrowana lub inna forma, we własnym zakresie).
