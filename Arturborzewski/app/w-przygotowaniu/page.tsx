import type { Metadata } from 'next'
import site from '../../content/site.json'

const k = site.kancelaria

export const metadata: Metadata = {
  title: `W przygotowaniu | ${k.nazwa}`,
  description: 'Ta sekcja strony jest w przygotowaniu.',
  robots: { index: false, follow: true },
  alternates: { canonical: `${k.url}/w-przygotowaniu/` },
}

export default function WPrzygotowaniuPage() {
  return (
    <div className="min-h-screen bg-black text-white font-sans">
      <div className="max-w-4xl mx-auto px-6 py-40">
        <div className="text-yellow-500 tracking-[0.3em] uppercase text-sm mb-6">W przygotowaniu</div>
        <h1 className="text-5xl md:text-7xl font-serif leading-tight mb-10">Ta sekcja jest w przygotowaniu</h1>
        <p className="text-zinc-400 text-xl leading-9 mb-16">
          Pracujemy nad szczegółami tej specjalizacji. W międzyczasie chętnie odpowiemy na Twoje
          pytania — zapraszamy do kontaktu z kancelarią.
        </p>

        <div className="border-t border-white/5 pt-16 flex flex-wrap gap-4">
          <a
            href="/#contact"
            className="inline-block bg-yellow-500 text-black px-8 py-4 rounded-full font-semibold hover:scale-105 transition duration-300"
          >
            Umów konsultację
          </a>
          <a
            href="/"
            className="inline-block border border-white/15 text-white px-8 py-4 rounded-full font-semibold hover:border-yellow-500/40 transition duration-300"
          >
            Powrót na stronę główną
          </a>
        </div>
      </div>
    </div>
  )
}
