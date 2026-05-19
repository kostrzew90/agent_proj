import site from '../content/site.json'
import ContactForm from './ContactForm'
import LogoImage from './LogoImage'
import { AnimatedSection } from './AnimatedSection'
import { AnimatedCardGrid, AnimatedCardItem } from './AnimatedCards'
import { AnimatedHeroContainer, AnimatedHeroLine } from './AnimatedHero'

export default function HomePage() {
  return (
    <div className="min-h-screen bg-black text-white font-sans overflow-x-hidden">

      {/* STICKY MOBILE CTA */}
      <div className="fixed bottom-0 left-0 right-0 lg:hidden z-50 bg-black/95 border-t border-white/10 p-4 flex gap-3">
        <a
          href={`tel:${site.kancelaria.telefonRaw}`}
          className="flex-1 bg-yellow-500 text-black text-center py-3 rounded-full font-semibold text-sm"
        >
          Zadzwoń
        </a>
        <a href="#contact" className="flex-1 border border-yellow-500/40 text-center py-3 rounded-full text-sm">
          Napisz
        </a>
      </div>

      {/* HEADER */}
      <header className="fixed top-0 left-0 w-full z-50 backdrop-blur-xl bg-black/60 border-b border-white/5">
        <div className="max-w-7xl mx-auto px-6 h-24 flex items-center justify-between">
          <div className="flex items-center">
            <LogoImage alt={site.kancelaria.nazwa} />
          </div>
          <nav className="hidden lg:flex items-center gap-10 text-sm tracking-wide">
            <a href="#about" className="hover:text-yellow-400 transition duration-300">O kancelarii</a>
            <a href="#lawyer" className="hover:text-yellow-400 transition duration-300">O adwokacie</a>
            <a href="#services" className="hover:text-yellow-400 transition duration-300">Specjalizacje</a>
            <a href="#clients" className="hover:text-yellow-400 transition duration-300">Klienci</a>
            <a href="#contact" className="hover:text-yellow-400 transition duration-300">Kontakt</a>
          </nav>
          <div className="flex items-center gap-4">
            <a
              href="#contact"
              className="hidden lg:block bg-yellow-500 text-black px-6 py-3 rounded-full font-medium hover:scale-105 transition duration-300 shadow-[0_0_40px_rgba(234,179,8,0.15)]"
            >
              Konsultacja
            </a>
            <button className="lg:hidden flex flex-col gap-1.5" aria-label="Menu">
              <span className="w-7 h-[2px] bg-yellow-400 rounded-full"></span>
              <span className="w-7 h-[2px] bg-yellow-400 rounded-full"></span>
              <span className="w-7 h-[2px] bg-yellow-400 rounded-full"></span>
            </button>
          </div>
        </div>
      </header>

      {/* HERO */}
      <section className="relative min-h-screen flex items-center pt-32">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(234,179,8,0.15),transparent_35%)]"></div>
        <div className="max-w-7xl mx-auto px-6 grid lg:grid-cols-2 gap-20 items-center relative z-10">
          <AnimatedHeroContainer>
            <AnimatedHeroLine>
              <div className="text-yellow-500 tracking-[0.4em] uppercase text-sm mb-8">
                Nowoczesna kancelaria prawna
              </div>
            </AnimatedHeroLine>
            <AnimatedHeroLine>
              <h1 className="text-5xl md:text-7xl font-serif leading-none mb-8">
                Strategia.<br />Dyskrecja.<br />Skuteczność.
              </h1>
            </AnimatedHeroLine>
            <AnimatedHeroLine>
              <p className="text-zinc-400 text-lg leading-8 max-w-xl mb-10">
                {site.kancelaria.nazwa} zapewnia kompleksową obsługę prawną klientów
                indywidualnych oraz przedsiębiorców.
              </p>
            </AnimatedHeroLine>
            <AnimatedHeroLine>
              <div className="flex flex-col sm:flex-row gap-5">
                <a
                  href="#contact"
                  className="bg-yellow-500 text-black px-8 py-4 rounded-full font-semibold hover:scale-105 transition duration-300 text-center"
                >
                  Skontaktuj się
                </a>
                <a
                  href="#services"
                  className="border border-white/10 px-8 py-4 rounded-full hover:border-yellow-500/40 transition duration-300 text-center"
                >
                  Zakres usług
                </a>
              </div>
            </AnimatedHeroLine>
          </AnimatedHeroContainer>

          <AnimatedSection className="relative flex justify-center">
            <div className="absolute w-96 h-96 bg-yellow-500/10 blur-3xl rounded-full"></div>
            <div className="relative border border-yellow-500/20 bg-white/5 backdrop-blur-2xl rounded-[40px] p-6 shadow-2xl max-w-xl w-full hover:scale-[1.01] transition duration-700">
              <img
                src="/images/hero-lawyer.jpg"
                alt={site.kancelaria.nazwa}
                className="rounded-[32px] w-full h-[700px] object-cover"
              />
              <div className="absolute inset-0 rounded-[32px] bg-gradient-to-t from-black/60 via-transparent to-transparent"></div>
              <div className="absolute bottom-8 left-8 right-8">
                <LogoImage
                  alt={site.kancelaria.nazwa}
                  src="/images/logo-mono.png"
                  className="w-full max-w-xs object-contain"
                />
              </div>
            </div>
          </AnimatedSection>
        </div>
      </section>

      {/* ABOUT */}
      <section id="about" className="py-32 border-t border-white/5">
        <AnimatedSection>
          <div className="max-w-7xl mx-auto px-6 grid lg:grid-cols-2 gap-20 items-start">
            <div>
              <div className="text-yellow-500 tracking-[0.3em] uppercase text-sm mb-6">O kancelarii</div>
              <h2 className="text-4xl md:text-6xl font-serif leading-tight">
                Nowoczesne podejście do obsługi prawnej.
              </h2>
            </div>
            <div className="space-y-8 text-zinc-400 leading-8 text-lg">
              <p>Kancelaria została zaprojektowana z myślą o klientach oczekujących skuteczności, transparentności i sprawnej komunikacji.</p>
              <p>Wykorzystujemy nowoczesne rozwiązania technologiczne wspierające analizę dokumentów oraz bezpieczny obieg informacji.</p>
              <div className="text-zinc-500 text-sm space-y-1">
                <div>{site.kancelaria.adres}</div>
                <div>{site.kancelaria.godziny}</div>
                <div>NIP: {site.kancelaria.nip}</div>
              </div>
            </div>
          </div>
        </AnimatedSection>
      </section>

      {/* O ADWOKACIE */}
      <section id="lawyer" className="py-32 bg-zinc-950 border-y border-white/5">
        <div className="max-w-7xl mx-auto px-6 grid lg:grid-cols-2 gap-20 items-start">
          <AnimatedSection>
            <div className="text-yellow-500 tracking-[0.3em] uppercase text-sm mb-6">O adwokacie</div>
            <h2 className="text-4xl md:text-6xl font-serif leading-tight mb-10">
              {site.oAdwokacie.tytul}
            </h2>
            <div className="space-y-6 text-zinc-400 leading-8 text-lg">
              {site.oAdwokacie.bio.map((p, i) => <p key={i}>{p}</p>)}
            </div>
          </AnimatedSection>
          <AnimatedCardGrid className="space-y-4">
            {site.oAdwokacie.doswiadczenie.map((item) => (
              <AnimatedCardItem key={item}>
                <div className="flex items-start gap-4 rounded-[20px] border border-white/5 bg-white/[0.02] p-6">
                  <div className="text-yellow-400 text-xl mt-1 shrink-0">✦</div>
                  <p className="text-zinc-300 leading-7">{item}</p>
                </div>
              </AnimatedCardItem>
            ))}
          </AnimatedCardGrid>
        </div>
      </section>

      {/* SERVICES */}
      <section id="services" className="py-32 border-y border-white/5">
        <div className="max-w-7xl mx-auto px-6">
          <AnimatedSection className="mb-20">
            <div className="text-yellow-500 tracking-[0.3em] uppercase text-sm mb-6">Specjalizacje</div>
            <h2 className="text-4xl md:text-6xl font-serif">Zakres obsługi kancelarii</h2>
          </AnimatedSection>
          <AnimatedCardGrid className="grid md:grid-cols-2 xl:grid-cols-3 gap-8">
            {site.specjalizacje.map((item) => (
              <AnimatedCardItem key={item.slug}>
                <a
                  href={`/${item.slug}/`}
                  className="group rounded-[30px] border border-white/5 bg-white/[0.02] p-10 hover:border-yellow-500/30 hover:-translate-y-2 transition duration-500 block h-full"
                >
                  <div className="w-14 h-14 rounded-2xl bg-yellow-500/10 border border-yellow-500/20 mb-8 flex items-center justify-center text-yellow-400 text-xl">
                    ✦
                  </div>
                  <h3 className="text-2xl font-serif mb-5 group-hover:text-yellow-400 transition">
                    {item.nazwa}
                  </h3>
                  <p className="text-zinc-400 leading-7">{item.opis}</p>
                </a>
              </AnimatedCardItem>
            ))}
          </AnimatedCardGrid>
        </div>
      </section>

      {/* KLIENCI */}
      <section id="clients" className="py-32 bg-zinc-950 border-y border-white/5">
        <div className="max-w-7xl mx-auto px-6">
          <AnimatedSection className="mb-20">
            <div className="text-yellow-500 tracking-[0.3em] uppercase text-sm mb-6">Klienci</div>
            <h2 className="text-4xl md:text-6xl font-serif">Z kim współpracuję</h2>
          </AnimatedSection>
          <AnimatedCardGrid className="grid md:grid-cols-2 xl:grid-cols-4 gap-6">
            {site.klienci.map((item) => (
              <AnimatedCardItem key={item.nazwa}>
                <div className="rounded-[28px] border border-white/5 bg-white/[0.02] p-8 h-full">
                  <div className="text-3xl mb-6">{item.ikona}</div>
                  <h3 className="text-xl font-serif mb-3">{item.nazwa}</h3>
                  <p className="text-zinc-400 leading-7 text-sm">{item.opis}</p>
                </div>
              </AnimatedCardItem>
            ))}
          </AnimatedCardGrid>
        </div>
      </section>

      {/* WYRÓŻNIENIA */}
      <section id="distinctions" className="py-32 border-y border-white/5">
        <div className="max-w-7xl mx-auto px-6">
          <AnimatedSection className="mb-20">
            <div className="text-yellow-500 tracking-[0.3em] uppercase text-sm mb-6">Dlaczego my</div>
            <h2 className="text-4xl md:text-6xl font-serif">Co wyróżnia kancelarię</h2>
          </AnimatedSection>
          <AnimatedCardGrid className="grid md:grid-cols-2 xl:grid-cols-3 gap-8">
            {site.wyroznienia.map((item) => (
              <AnimatedCardItem key={item.tytul}>
                <div className="rounded-[30px] border border-white/5 bg-white/[0.02] p-10 h-full">
                  <div className="text-2xl mb-6">{item.ikona}</div>
                  <h3 className="text-2xl font-serif mb-4">{item.tytul}</h3>
                  <p className="text-zinc-400 leading-7">{item.opis}</p>
                </div>
              </AnimatedCardItem>
            ))}
          </AnimatedCardGrid>
        </div>
      </section>

      {/* CASES */}
      <section id="cases" className="py-32 bg-zinc-950 border-y border-white/5">
        <div className="max-w-7xl mx-auto px-6">
          <AnimatedSection className="mb-20">
            <div className="text-yellow-500 tracking-[0.3em] uppercase text-sm mb-6">Realizacje</div>
            <h2 className="text-4xl md:text-6xl font-serif">Wybrane obszary działań</h2>
          </AnimatedSection>
          <AnimatedCardGrid className="grid lg:grid-cols-3 gap-8">
            {site.realizacje.map((item, index) => (
              <AnimatedCardItem key={item}>
                <div className="rounded-[30px] overflow-hidden border border-white/5 bg-black h-full">
                  <img
                    src={`/images/cases/case-${index + 1}.jpg`}
                    alt={item}
                    className="w-full h-72 object-cover"
                  />
                  <div className="p-8">
                    <div className="text-yellow-500 uppercase tracking-[0.3em] text-xs mb-4">Case Study</div>
                    <h3 className="text-2xl font-serif leading-relaxed">{item}</h3>
                  </div>
                </div>
              </AnimatedCardItem>
            ))}
          </AnimatedCardGrid>
        </div>
      </section>

      {/* CONTACT */}
      <section id="contact" className="py-32 pb-40 lg:pb-32">
        <div className="max-w-7xl mx-auto px-6 grid lg:grid-cols-2 gap-20 items-start">
          <AnimatedSection>
            <div className="text-yellow-500 tracking-[0.3em] uppercase text-sm mb-6">Kontakt</div>
            <h2 className="text-4xl md:text-6xl font-serif mb-10 leading-tight">
              Skontaktuj się z kancelarią.
            </h2>
            <div className="space-y-10 text-lg">
              <div>
                <div className="text-yellow-500 mb-2 uppercase tracking-[0.2em] text-sm">Email kancelarii</div>
                <a href={`mailto:${site.kancelaria.email}`} className="text-zinc-300 hover:text-yellow-400 transition">
                  {site.kancelaria.email}
                </a>
              </div>
              <div>
                <div className="text-yellow-500 mb-2 uppercase tracking-[0.2em] text-sm">Biuro</div>
                <a href={`mailto:${site.kancelaria.biuro}`} className="text-zinc-300 hover:text-yellow-400 transition">
                  {site.kancelaria.biuro}
                </a>
              </div>
              <div>
                <div className="text-yellow-500 mb-2 uppercase tracking-[0.2em] text-sm">Telefon</div>
                <a href={`tel:${site.kancelaria.telefonRaw}`} className="text-zinc-300 hover:text-yellow-400 transition">
                  {site.kancelaria.telefon}
                </a>
              </div>
            </div>
          </AnimatedSection>
          <AnimatedSection>
            <ContactForm />
          </AnimatedSection>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="border-t border-white/5 py-10 text-zinc-500">
        <div className="max-w-7xl mx-auto px-6 flex flex-col md:flex-row items-center justify-between gap-6 text-sm">
          <LogoImage
            alt={site.kancelaria.nazwa}
            src="/images/logo-skrocone.png"
            className="h-12 w-auto object-contain opacity-70"
          />
          <div>© {new Date().getFullYear()} {site.kancelaria.nazwa}</div>
          <div>Nowoczesna obsługa prawna klientów indywidualnych i biznesowych.</div>
        </div>
      </footer>

    </div>
  )
}
