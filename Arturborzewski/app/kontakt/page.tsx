import type { Metadata } from 'next'
import site from '../../content/site.json'
import ContactForm from '../ContactForm'

export const metadata: Metadata = {
  title: `Kontakt | ${site.kancelaria.nazwa}`,
  description: `Skontaktuj się z kancelarią adwokacką w ${site.kancelaria.miasto}. ${site.kancelaria.telefon}`,
  alternates: { canonical: `${site.kancelaria.url}/kontakt/` },
}

export default function KontaktPage() {
  return (
    <div className="min-h-screen bg-black text-white font-sans">
      <div className="max-w-7xl mx-auto px-6 py-40 grid lg:grid-cols-2 gap-20 items-start">
        <div>
          <div className="text-yellow-500 tracking-[0.3em] uppercase text-sm mb-6">Kontakt</div>
          <h1 className="text-5xl md:text-6xl font-serif mb-10 leading-tight">
            Skontaktuj się z kancelarią.
          </h1>
          <div className="space-y-8 text-lg">
            <div>
              <div className="text-yellow-500 mb-2 uppercase tracking-[0.2em] text-sm">Adres</div>
              <div className="text-zinc-300">{site.kancelaria.adres}</div>
            </div>
            <div>
              <div className="text-yellow-500 mb-2 uppercase tracking-[0.2em] text-sm">Godziny</div>
              <div className="text-zinc-300">{site.kancelaria.godziny}</div>
            </div>
            <div>
              <div className="text-yellow-500 mb-2 uppercase tracking-[0.2em] text-sm">Telefon</div>
              <a href={`tel:${site.kancelaria.telefonRaw}`} className="text-zinc-300 hover:text-yellow-400 transition">
                {site.kancelaria.telefon}
              </a>
            </div>
            <div>
              <div className="text-yellow-500 mb-2 uppercase tracking-[0.2em] text-sm">Email</div>
              <a href={`mailto:${site.kancelaria.email}`} className="text-zinc-300 hover:text-yellow-400 transition">
                {site.kancelaria.email}
              </a>
            </div>
          </div>
        </div>
        <ContactForm />
      </div>
    </div>
  )
}
