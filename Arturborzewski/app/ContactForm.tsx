'use client'

import { useEffect, useRef, useState } from 'react'
import Script from 'next/script'

export default function ContactForm() {
  const csrfRef = useRef<HTMLInputElement>(null)
  const [status, setStatus] = useState<'idle' | 'sending' | 'success' | 'error'>('idle')

  useEffect(() => {
    // Fetch CSRF token from PHP on mount
    fetch('/get-csrf.php')
      .then(r => r.json())
      .then(data => {
        if (csrfRef.current) csrfRef.current.value = data.token
      })
      .catch(() => {}) // Don't block form if PHP unavailable (dev mode)
  }, [])

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setStatus('sending')
    const form = e.currentTarget
    const data = new FormData(form)

    try {
      const res = await fetch('/contact.php', { method: 'POST', body: data })
      const json = await res.json()
      setStatus(json.success ? 'success' : 'error')
    } catch {
      setStatus('error')
    }
  }

  return (
    <div className="rounded-[40px] border border-white/5 bg-white/[0.02] p-8 md:p-12 backdrop-blur-xl">
      {status === 'success' ? (
        <div className="text-center py-12">
          <div className="text-yellow-400 text-4xl mb-4">✓</div>
          <p className="text-xl font-serif">Wiadomość wysłana.</p>
          <p className="text-zinc-400 mt-2">Odezwiemy się wkrótce.</p>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="grid gap-6">
          {/* CSRF */}
          <input type="hidden" name="csrf_token" ref={csrfRef} />
          {/* Honeypot — hidden from humans, visible to bots */}
          <input type="text" name="website" className="hidden" tabIndex={-1} autoComplete="off" />

          <input
            name="imie"
            required
            placeholder="Imię i nazwisko"
            className="h-16 rounded-2xl bg-black border border-white/10 px-6 outline-none focus:border-yellow-500/40 text-white"
          />
          <input
            name="email"
            type="email"
            required
            placeholder="Adres e-mail"
            className="h-16 rounded-2xl bg-black border border-white/10 px-6 outline-none focus:border-yellow-500/40 text-white"
          />
          <textarea
            name="wiadomosc"
            required
            rows={6}
            placeholder="Opisz swoją sprawę"
            className="rounded-2xl bg-black border border-white/10 px-6 py-5 outline-none focus:border-yellow-500/40 text-white resize-none"
          />

          {/* Cloudflare Turnstile — replace sitekey after registering at dash.cloudflare.com */}
          <div
            className="cf-turnstile"
            data-sitekey="0x4AAAAAAA_REPLACE_WITH_REAL_SITEKEY"
            data-theme="dark"
          ></div>

          {/* RODO consent checkbox */}
          <label className="flex items-start gap-3 text-sm text-zinc-400 cursor-pointer">
            <input type="checkbox" name="rodo" required className="mt-1 accent-yellow-500" />
            <span>
              Wyrażam zgodę na przetwarzanie moich danych osobowych w celu odpowiedzi na zapytanie,
              zgodnie z{' '}
              <a href="/polityka-prywatnosci/" className="text-yellow-500 hover:underline">
                polityką prywatności
              </a>
              .
            </span>
          </label>

          {status === 'error' && (
            <p className="text-red-400 text-sm">Wystąpił błąd. Proszę spróbować ponownie lub napisać bezpośrednio na email kancelarii.</p>
          )}

          <button
            type="submit"
            disabled={status === 'sending'}
            className="h-16 rounded-full bg-yellow-500 text-black font-semibold hover:scale-[1.02] transition duration-300 disabled:opacity-60"
          >
            {status === 'sending' ? 'Wysyłanie...' : 'Wyślij wiadomość'}
          </button>
        </form>
      )}

      <Script
        src="https://challenges.cloudflare.com/turnstile/v0/api.js"
        strategy="lazyOnload"
      />
    </div>
  )
}
