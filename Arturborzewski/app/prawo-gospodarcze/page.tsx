import type { Metadata } from 'next'
import site from '../../content/site.json'

const spec = site.specjalizacje.find(s => s.slug === 'prawo-gospodarcze')!

export const metadata: Metadata = {
  title: `${spec.nazwa} | ${site.kancelaria.nazwa}`,
  description: `${spec.opis} Kancelaria adwokacka w ${site.kancelaria.miasto}.`,
  alternates: { canonical: `${site.kancelaria.url}/prawo-gospodarcze/` },
}

export default function PrawoGospodarczePage() {
  return (
    <div className="min-h-screen bg-black text-white font-sans">
      <div className="max-w-4xl mx-auto px-6 py-40">
        <div className="text-yellow-500 tracking-[0.3em] uppercase text-sm mb-6">Specjalizacja</div>
        <h1 className="text-5xl md:text-7xl font-serif leading-tight mb-10">{spec.nazwa}</h1>
        <p className="text-zinc-400 text-xl leading-9 mb-16">{spec.opis}</p>

        <div className="border-t border-white/5 pt-16">
          <p className="text-zinc-500 mb-8">
            Kancelaria {site.kancelaria.nazwa} obsługuje sprawy z zakresu {spec.nazwa.toLowerCase()} w{' '}
            {site.kancelaria.miasto} i okolicach.
          </p>
          <a
            href="/#contact"
            className="inline-block bg-yellow-500 text-black px-8 py-4 rounded-full font-semibold hover:scale-105 transition duration-300"
          >
            Umów konsultację
          </a>
        </div>
      </div>
    </div>
  )
}
