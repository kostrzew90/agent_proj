import type { Metadata } from 'next'
import site from '../../content/site.json'

const k = site.kancelaria

export const metadata: Metadata = {
  title: `Polityka prywatności | ${k.nazwa}`,
  description: `Zasady przetwarzania danych osobowych (RODO) w ${k.nazwa}.`,
  alternates: { canonical: `${k.url}/polityka-prywatnosci/` },
}

export default function PolitykaPrywatnosciPage() {
  return (
    <div className="min-h-screen bg-black text-white font-sans">
      <div className="max-w-4xl mx-auto px-6 py-40">
        <div className="text-yellow-500 tracking-[0.3em] uppercase text-sm mb-6">Informacje prawne</div>
        <h1 className="text-5xl md:text-7xl font-serif leading-tight mb-6">Polityka prywatności</h1>
        <p className="text-zinc-500 mb-16">Ostatnia aktualizacja: 28 lipca 2026 r.</p>

        <div className="space-y-14 text-zinc-300 leading-8 text-lg">
          <section>
            <h2 className="text-2xl font-serif text-white mb-4">1. Administrator danych osobowych</h2>
            <p>
              Administratorem Twoich danych osobowych jest <strong>{k.nazwa}</strong>, {k.adres},
              NIP: {k.nip}. Kontakt w sprawach ochrony danych:{' '}
              <a href={`mailto:${k.email}`} className="text-yellow-500 hover:underline">{k.email}</a>.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-serif text-white mb-4">2. Jakie dane zbieramy</h2>
            <p>
              Za pośrednictwem formularza kontaktowego zbieramy dane, które podajesz dobrowolnie:
              imię i nazwisko, adres e-mail oraz treść wiadomości. Nie zbieramy danych w sposób
              automatyczny w celach analitycznych ani marketingowych.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-serif text-white mb-4">3. Cel i podstawa prawna przetwarzania</h2>
            <p>Twoje dane przetwarzamy w celu:</p>
            <ul className="list-disc pl-6 mt-4 space-y-2">
              <li>
                udzielenia odpowiedzi na przesłane zapytanie oraz podjęcia kontaktu — na podstawie
                Twojej zgody (art. 6 ust. 1 lit. a RODO) oraz naszego prawnie uzasadnionego interesu
                polegającego na obsłudze korespondencji (art. 6 ust. 1 lit. f RODO);
              </li>
              <li>
                podjęcia działań przed zawarciem ewentualnej umowy o świadczenie pomocy prawnej, na
                Twoje żądanie (art. 6 ust. 1 lit. b RODO).
              </li>
            </ul>
          </section>

          <section>
            <h2 className="text-2xl font-serif text-white mb-4">4. Okres przechowywania danych</h2>
            <p>
              Dane przechowujemy przez czas niezbędny do udzielenia odpowiedzi i obsługi sprawy, a po
              jej zakończeniu — do czasu przedawnienia ewentualnych roszczeń lub do momentu cofnięcia
              zgody, w zależności od tego, co nastąpi wcześniej.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-serif text-white mb-4">5. Odbiorcy danych</h2>
            <p>
              Twoje dane mogą być powierzone dostawcy usług hostingowych i poczty elektronicznej,
              działającemu na nasze zlecenie jako podmiot przetwarzający, w zakresie niezbędnym do
              utrzymania strony i obsługi korespondencji. Dane nie są sprzedawane ani udostępniane
              podmiotom trzecim w celach marketingowych.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-serif text-white mb-4">6. Pliki cookies</h2>
            <p>
              Strona wykorzystuje wyłącznie niezbędny plik cookie sesji (utrzymanie bezpieczeństwa
              formularza kontaktowego — ochrona przed nadużyciami). Nie stosujemy plików cookies
              analitycznych, marketingowych ani śledzących. Nie korzystamy z zewnętrznych narzędzi
              analityki ruchu.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-serif text-white mb-4">7. Twoje prawa</h2>
            <p>W związku z przetwarzaniem danych przysługuje Ci prawo do:</p>
            <ul className="list-disc pl-6 mt-4 space-y-2">
              <li>dostępu do swoich danych oraz otrzymania ich kopii,</li>
              <li>sprostowania (poprawiania) danych,</li>
              <li>usunięcia danych,</li>
              <li>ograniczenia przetwarzania,</li>
              <li>wniesienia sprzeciwu wobec przetwarzania,</li>
              <li>przenoszenia danych,</li>
              <li>cofnięcia zgody w dowolnym momencie (bez wpływu na zgodność z prawem przetwarzania sprzed cofnięcia),</li>
              <li>
                wniesienia skargi do organu nadzorczego — Prezesa Urzędu Ochrony Danych Osobowych
                (ul. Stawki 2, 00-193 Warszawa).
              </li>
            </ul>
          </section>

          <section>
            <h2 className="text-2xl font-serif text-white mb-4">8. Przekazywanie danych poza EOG</h2>
            <p>
              Nie przekazujemy Twoich danych osobowych do państw trzecich ani organizacji
              międzynarodowych poza Europejski Obszar Gospodarczy.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-serif text-white mb-4">9. Dobrowolność podania danych</h2>
            <p>
              Podanie danych jest dobrowolne, jednak niezbędne do udzielenia odpowiedzi na zapytanie
              przesłane przez formularz kontaktowy.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-serif text-white mb-4">10. Kontakt</h2>
            <p>
              We wszelkich sprawach dotyczących przetwarzania danych osobowych możesz skontaktować się
              z nami pod adresem{' '}
              <a href={`mailto:${k.email}`} className="text-yellow-500 hover:underline">{k.email}</a>.
            </p>
          </section>
        </div>

        <div className="border-t border-white/5 pt-12 mt-16">
          <a
            href="/"
            className="inline-block bg-yellow-500 text-black px-8 py-4 rounded-full font-semibold hover:scale-105 transition duration-300"
          >
            Powrót na stronę główną
          </a>
        </div>
      </div>
    </div>
  )
}
