# Scenariusze rozmów walidacyjnych

**Data:** 2026-07-10
**Kontekst:** patrz `2026-07-10-walidacja-dwutorowa-design.md`

Dwa scenariusze — po jednym na tor. Prowadzić jako rozmowę, nie ankietę: pytania to szkielet, nie skrypt do odczytania. Notować odpowiedzi na bieżąco (miejsce na notatki pod każdym blokiem).

---

## Scenariusz A — gate zero ze znajomym przedsiębiorcą (Tor 1)

### Otwarcie (bez pitchu)

Nie zaczynać od "mam pomysł na system". Zacząć od ciekawości procesem — pitch pada dopiero po zebraniu faktów, w bloku "pieniądze".

- "Opowiedz mi jak wygląda Twój dzień z pocztą / fakturami — co robisz od rana."
- "Ile czasu w tygodniu szacujesz, że to zajmuje?"

Notatki: _______________________________________________

### Proces mailowy — fakty, nie opinie

Dlaczego: potrzebujemy realnego wolumenu i kategorii, żeby skalibrować progi sukcesu (patrz spec: "firma z 10 mailami/tydz. dostaje proporcjonalnie niższy próg").

- Ile masz skrzynek pocztowych i jakich (Gmail, wp.pl, inne)? Które faktycznie sprawdzasz codziennie?
- Ile maili dostajesz dziennie / tygodniowo — realnie, nie z głowy: otwórz skrzynkę i policzmy razem.
- **Pokaż mi ostatnie 5 maili w skrzynce.** Dla każdego: co to za mail, i co z nim faktycznie zrobiłeś (odpowiedziałeś, zignorowałeś, przekazałeś dalej, zapisałeś sobie gdzieś)?
- Jakie kategorie maili się powtarzają (zapytania ofertowe, faktury od dostawców, reklamacje, umowy, spam)?
- Kiedy ostatnio coś Ci umknęło albo odpowiedziałeś za późno — co się stało?

Notatki: _______________________________________________

### Faktury — fakty, nie opinie

Dlaczego: szablon faktury i skoroszyt muszą pasować do tego, co on faktycznie robi, nie do tego, co "byłoby fajne".

- Ile faktur wystawiasz miesięcznie — realna liczba z ostatniego miesiąca?
- W czym dziś wystawiasz faktury (Excel, jakiś program, ręcznie)?
- **Pokaż mi ostatnią wystawioną fakturę** i mail, który do niej doprowadził (zapytanie klienta, zamówienie, cokolwiek). Co dokładnie musiałeś zrobić między tym mailem a fakturą?
- Co w tym procesie najbardziej Cię wkurza / zabiera najwięcej czasu?

Notatki: _______________________________________________

### Skoroszyt / zbiorcza lista

Dlaczego: to konkretny artefakt, który ma powstać — musi mieć realne kolumny i realnego odbiorcę, nie wyobrażone.

- Co dokładnie ma się znaleźć w tym skoroszycie? Poproś o wymienienie kolumn, jakby miał je podyktować teraz.
- Kto oprócz Ciebie do niego zagląda? Jak często?
- Czy masz dziś jakąkolwiek wersję tego (choćby prowizoryczną w Excelu)? Pokaż.

Notatki: _______________________________________________

### Pieniądze — wprost

Dlaczego: to jest właściwy test sygnału. Nie pytać "czy byłbyś zainteresowany" — podać cenę i patrzeć na reakcję.

- "Zrobienie tego kosztowałoby [1,5–3 tys. zł] za wdrożenie plus [100–200 zł]/mc za utrzymanie. Jak to brzmi?"
- Obserwować reakcję, nie tylko słowa: czy pyta o szczegóły / termin startu, czy zmienia temat, czy mówi "muszę pomyśleć".
- Jeśli wykręt: "co dokładnie musiałbyś zobaczyć, żeby powiedzieć tak?" — zapisać odpowiedź dosłownie, nie interpretować.
- Kiedy realnie mógłbyś zapłacić za pierwszy miesiąc — teraz, po pierwszym tygodniu testów, po czymś innym?

Notatki: _______________________________________________

### Zgoda na przetwarzanie maili przez LLM w chmurze

Wymagane — bez tego tor nie rusza technicznie.

- Wyjaśnić wprost: treść maili (i danych w nich) będzie przechodzić przez API modelu językowego w chmurze (Gemini/Groq) w celu klasyfikacji i streszczenia.
- Zapytać: czy w tych skrzynkach mogą pojawiać się dane, które nie powinny nigdzie wychodzić (dane osobowe klientów wrażliwe, dane finansowe firm trzecich, cokolwiek objęte NDA)?
- Zapisać zgodę wprost — data i forma (mail, wiadomość, nagranie rozmowy).

Zgoda uzyskana: TAK / NIE — data: _______ forma: _______________________

### Checklist rzeczy do zebrania po rozmowie

- [ ] Dostęp: Gmail API (OAuth) i/lub dane IMAP do wp.pl
- [ ] Szablon faktury (plik lub przykład)
- [ ] 5–10 przykładowych maili (do testowania klasyfikacji)
- [ ] Lista kategorii maili ustalona wspólnie
- [ ] Lista kolumn skoroszytu ustalona wspólnie
- [ ] Potwierdzona kwota i termin pierwszej płatności

### Czerwone flagi (tor umiera / słabnie)

- Nie chce podać konkretnej kwoty ani terminu płatności, mówi "zobaczymy jak zadziała, to zapłacę" (odwrócona kolejność — sygnał braku realnego zaangażowania).
- Nie potrafi pokazać procesu na żywo — "no generalnie tak to wygląda" bez otwarcia skrzynki/faktury.
- "Fajny pomysł, odezwę się" — brak deklaracji konkretnej daty/kroku.
- Wolumen maili/faktur jest tak niski (np. 2-3 maile dziennie, 1 faktura miesięcznie), że automatyzacja nie ma sensu ekonomicznego dla żadnej ze stron.
- Reaguje na cenę pytaniem "a nie mogłoby być za darmo, przetestujemy i potem zapłacę" — brak sygnału gotowości płatności.

---

## Scenariusz B — discovery z Borzewskim (Tor 2)

Zasada nadrzędna: **obserwacja zamiast opinii.** Nie pytać "czy to byłoby przydatne" ani "czy używałbyś takiego systemu". Zamiast tego: "pokaż mi ostatnie pismo", "co robisz dalej?" — i patrzeć, nie podpowiadać.

Pitch (propozycja design partnerstwa) pada dopiero na końcu, i tylko jeśli ból jest potwierdzony faktami z rozmowy.

### Otwarcie

- "Chciałbym zobaczyć, jak wygląda u Ciebie normalny dzień z korespondencją — pokaż mi, jak to działa na żywym przykładzie, najlepiej dzisiejszym albo z tego tygodnia."
- Poprosić, żeby po prostu pokazał proces krok po kroku, tak jakby robił to bez Ciebie w pokoju.

Notatki: _______________________________________________

### Obieg korespondencji

Dlaczego: trzeba wiedzieć, jaki jest realny punkt wejścia dla systemu (skan? e-Doręczenia? papier?) — od tego zależy MVP.

- **Pokaż mi ostatnie pismo, które wpłynęło do kancelarii.** Skąd przyszło — e-Doręczenia, poczta papierowa, skan, mail?
- Kto je fizycznie odbiera / otwiera jako pierwszy?
- Co się z nim dzieje zaraz potem — gdzie ląduje (segregator, skan, mail do adwokata, nic)?
- Ile z tych kanałów (e-Doręczenia / papier / skan / email) realnie obsługujecie tygodniowo — proporcje?

Notatki: _______________________________________________

### Terminy

Dlaczego: to jest sedno bólu z tezy Toru 2 — trzeba zobaczyć realny mechanizm, nie deklarowany.

- Kto w kancelarii wylicza terminy procesowe z pisma?
- Według czego liczy — na pamięć, kalendarz sądowy, jakiś program, kartka?
- **Pokaż mi, gdzie dziś zapisany jest najbliższy termin** — otwórz to, co normalnie otwierasz.
- Jak wygląda kalendarz kancelarii fizycznie — jeden wspólny, czy każdy ma swój?
- Kto pilnuje, żeby przypomnienie faktycznie zadziałało (telefon, sekretariat, nikt)?

Notatki: _______________________________________________

### Historia incydentu

Dlaczego: konkretna, przeszła sytuacja jest twardszym dowodem bólu niż każda deklaracja.

- "Opowiedz mi o ostatnim razie, kiedy termin był blisko przegapienia albo faktycznie się to zdarzyło."
- Co się wtedy stało krok po kroku? Kto to zauważył i kiedy?
- Ile to kosztowało — czasu, nerwów, pieniędzy, ewentualnie relacji z klientem?
- Jak często coś takiego się zdarza — raz w roku, częściej?

Notatki: _______________________________________________

### Skala

Dlaczego: potrzebne twarde liczby do oceny, czy problem jest wystarczająco duży, żeby budować pod niego produkt.

- Ile pism wpływa do kancelarii tygodniowo — licząc razem wszystkie kanały?
- Ile spraw prowadzicie równolegle w tej chwili?
- Ile osób w kancelarii zajmuje się obsługą korespondencji i terminów?

Notatki: _______________________________________________

### Pieniądze

Dlaczego: nawet przy modelu design-partner (za darmo/symbolicznie) trzeba znać realny budżet na software, żeby ocenić przyszły sufit cenowy.

- Co dziś płacicie za oprogramowanie kancelaryjne / systemy do zarządzania sprawami?
- Ile kosztuje Cię (w przybliżeniu) godzina pracy sekretariatu przy obsłudze pism i wyliczaniu terminów?
- Czy kiedykolwiek szukaliście / kupowaliście narzędzia do tego problemu? Co się z tym stało?

Notatki: _______________________________________________

### Propozycja design partnerstwa (dopiero teraz, jeśli ból potwierdzony)

Warunek: dopiero jeśli z powyższych bloków wynika realny, powtarzalny ból (nie pojedynczy incydent sprzed lat, nie "no teoretycznie mogłoby się zdarzyć").

- Przedstawić wprost: system czytający skan/PDF pisma, wyciągający datę i proponujący wpis do kalendarza z akceptacją człowieka — na razie bez integracji z e-Doręczeniami.
- Propozycja: używa za darmo albo symbolicznie w zamian za cotygodniowy feedback i zgodę na referencję.
- Zapytać wprost o gotowość na taki układ i o realny termin pierwszego testu (konkretna data, nie "kiedyś").

Notatki: _______________________________________________

### Prośba o polecenia

Zawsze na końcu, niezależnie od wyniku — potrzebne jako plan B jeśli ból u Borzewskiego okaże się marginalny.

- "Znasz 2-3 inne kancelarie, które mogłyby mieć podobny problem z terminami? Czy mógłbyś mnie polecić / przedstawić?"

Notatki: _______________________________________________

### Czerwone flagi (tor umiera / słabnie)

- Terminy pilnuje jeden konkretny program, który już mają i który działa dobrze — brak niezaspokojonej potrzeby.
- Wolumen pism jest bardzo niski (np. 2-3 tygodniowo) — problem za mały, żeby uzasadnić narzędzie.
- Wszystko deleguje aplikantowi/sekretariatowi i sam nie odczuwa bólu — decyzję o wdrożeniu podejmuje ktoś inny, kto może mieć inne priorytety.
- Historia incydentu jest odległa w czasie (lata temu) albo wymyślona na poczekaniu, nie potrafi opisać konkretnego przebiegu.
- Reaguje entuzjastycznie na propozycję ("super pomysł!") ale nie potrafi wskazać konkretnej daty pierwszego testu ani nie zgadza się na cotygodniowy feedback.
