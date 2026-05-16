# Kancelaria Adwokacka Artur Borzewski — strona www

## Jak dodać zdjęcie

1. Wrzuć plik (JPG lub PNG) do folderu `public/images/`
2. Uruchom `npm run build`
3. Wgraj folder `out/` na serwer przez FTP

Zdjęcia zostaną automatycznie zoptymalizowane do WebP przy każdym buildzie.

### Nazwy plików

| Plik | Gdzie się pojawia |
|------|------------------|
| `public/images/logo.png` | Nagłówek |
| `public/images/hero-lawyer.jpg` | Zdjęcie główne |
| `public/images/mecenas-artur.jpg` | Sekcja "O kancelarii" |
| `public/images/cases/case-1.jpg` | Realizacja 1 |
| `public/images/cases/case-2.jpg` | Realizacja 2 |
| `public/images/cases/case-3.jpg` | Realizacja 3 |

## Jak zmienić tekst / dane kontaktowe

Otwórz plik `content/site.json` i zmień wartości. Następnie zbuduj i wgraj na serwer.

## Jak uruchomić lokalnie

```bash
# Wymagany Node.js 18+
# Pobranie: https://nodejs.org

npm install        # tylko przy pierwszym uruchomieniu
npm run dev        # http://localhost:3000
```

## Jak wgrać na home.pl (deploy)

```bash
npm run build      # generuje folder out/
```

Następnie przez FTP (np. FileZilla):
1. Połącz się z serwerem home.pl
2. Wgraj całą zawartość folderu `out/` do katalogu `public_html/`

## Formularz kontaktowy — konfiguracja po wgraniu

1. Zaloguj się na [Cloudflare Turnstile](https://dash.cloudflare.com) i utwórz widget dla swojej domeny
2. W pliku `public/contact.php` zastąp:
   - `YOUR_TURNSTILE_SECRET_KEY` — secretem z Cloudflare
   - `SMTP_PASSWORD` — hasłem do konta email kancelarii
3. Ustaw zmienną środowiskową `NEXT_PUBLIC_TURNSTILE_SITEKEY` przed buildem (lub wpisz sitekey bezpośrednio w `app/ContactForm.tsx`)
4. Zainstaluj PHPMailer przez SSH lub panel home.pl: `composer install --no-dev`

## Konfiguracja SMTP na home.pl

- Host: `smtp.home.pl`
- Port: `587` (TLS)
- Login: adres email kancelarii
- Hasło: hasło do skrzynki

## Struktura projektu

```
app/          — kod strony (React/TypeScript)
content/      — teksty i dane (edytowalny JSON)
public/       — pliki statyczne (obrazy, PHP, konfiguracja)
scripts/      — narzędzia pomocnicze
out/          — wygenerowana strona (po npm run build)
```
