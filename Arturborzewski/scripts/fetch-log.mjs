// Diagnostyka: pobiera mail_error.log z serwera przez FTPS i wypisuje ostatnie linie.
// Uruchom: node --env-file=.env scripts/fetch-log.mjs
import { Client } from 'basic-ftp'
import { Writable } from 'stream'

const cfg = {
  host: process.env.FTP_HOST,
  user: process.env.FTP_USER,
  password: process.env.FTP_PASSWORD,
  port: Number(process.env.FTP_PORT ?? 21),
  secure: (process.env.FTP_SECURE ?? 'true') !== 'false',
  remoteDir: process.env.FTP_REMOTE_DIR ?? '/public_html',
}

const c = new Client(30000)
c.ftp.verbose = false
try {
  await c.access({
    host: cfg.host, port: cfg.port, user: cfg.user, password: cfg.password,
    secure: cfg.secure,
    secureOptions: cfg.secure ? { rejectUnauthorized: false } : undefined,
  })
  let buf = ''
  const w = new Writable({ write(chunk, _enc, cb) { buf += chunk.toString(); cb() } })
  await c.downloadTo(w, `${cfg.remoteDir}/mail_error.log`)
  console.log('=== mail_error.log (ostatnie 3000 znakow) ===')
  console.log(buf.slice(-3000))
} catch (e) {
  console.error('Blad pobierania logu:', e.message)
} finally {
  c.close()
}
