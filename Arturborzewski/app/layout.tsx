import type { Metadata } from 'next'
import { Playfair_Display, Inter } from 'next/font/google'
import './globals.css'
import site from '../content/site.json'

const inter = Inter({
  subsets: ['latin', 'latin-ext'],
  variable: '--font-inter',
  display: 'swap',
})

const playfair = Playfair_Display({
  subsets: ['latin', 'latin-ext'],
  variable: '--font-playfair',
  display: 'swap',
})

export const metadata: Metadata = {
  title: site.seo.tytul,
  description: site.seo.opis,
  keywords: site.seo.slowa,
  metadataBase: new URL(site.kancelaria.url),
  openGraph: {
    title: site.seo.tytul,
    description: site.seo.opis,
    url: site.kancelaria.url,
    siteName: site.kancelaria.nazwa,
    locale: 'pl_PL',
    type: 'website',
  },
  alternates: {
    canonical: site.kancelaria.url,
  },
  twitter: {
    card: 'summary',
    title: site.seo.tytul,
    description: site.seo.opis,
  },
}

const jsonLd = {
  '@context': 'https://schema.org',
  '@type': 'LegalService',
  name: site.kancelaria.nazwa,
  url: site.kancelaria.url,
  telephone: site.kancelaria.telefonRaw,
  email: site.kancelaria.email,
  areaServed: site.kancelaria.miasto,
  address: {
    '@type': 'PostalAddress',
    streetAddress: site.kancelaria.adres,
    addressLocality: site.kancelaria.miasto,
    addressCountry: 'PL',
  },
  geo: {
    '@type': 'GeoCoordinates',
    latitude: site.kancelaria.lat,
    longitude: site.kancelaria.lng,
  },
  openingHours: site.kancelaria.godzinySchema,
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pl" className={`${inter.variable} ${playfair.variable}`}>
      <head>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
        <link rel="icon" href="/favicon.ico" sizes="any" />
        <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
        <link rel="manifest" href="/site.webmanifest" />
      </head>
      <body className={`${inter.className} antialiased`}>{children}</body>
    </html>
  )
}
