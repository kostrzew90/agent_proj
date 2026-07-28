// Diagnostyka FTPS (jednorazowy test — plik do usunięcia po weryfikacji).
// Uruchom: node --env-file=.env scripts/deploy-test.mjs
// Potwierdza: połączenie FTPS, poprawność loginu/hasła, właściwy katalog zdalny,
// prawo zapisu. Wgrywa 1 mały plik, listuje katalog, po czym plik kasuje.

import { Client } from 'basic-ftp'
import { Readable } from 'stream'

const required = ['FTP_HOST', 'FTP_USER', 'FTP_PASSWORD']
const missing = required.filter((k) => !process.env[k])
if (missing.length > 0) {
  console.error(`❌ Brakuje zmiennych w .env: ${missing.join(', ')}`)
  process.exit(1)
}

const config = {
  host: process.env.FTP_HOST,
  user: process.env.FTP_USER,
  password: process.env.FTP_PASSWORD,
  port: Number(process.env.FTP_PORT ?? 21),
  secure: (process.env.FTP_SECURE ?? 'true') !== 'false',
  remoteDir: process.env.FTP_REMOTE_DIR ?? '/public_html',
}

const testName = `_deploytest_${Date.now()}.txt`

async function main() {
  const client = new Client(30000)
  client.ftp.verbose = false
  try {
    console.log(`ℹ️  Łączenie z ${config.host}:${config.port} (FTPS=${config.secure})...`)
    await client.access({
      host: config.host,
      port: config.port,
      user: config.user,
      password: config.password,
      secure: config.secure,
      secureOptions: config.secure ? { rejectUnauthorized: false } : undefined,
    })
    console.log('✅ Połączono i zalogowano.')

    await client.ensureDir(config.remoteDir)
    console.log(`✅ Katalog zdalny OK: ${config.remoteDir}`)

    // upload 1 małego pliku z pamięci
    const payload = Readable.from([`deploy test ${new Date().toISOString()}\n`])
    await client.uploadFrom(payload, testName)
    console.log(`✅ Wgrano plik testowy: ${testName}`)

    console.log('ℹ️  Zawartość katalogu zdalnego:')
    const list = await client.list()
    for (const item of list) {
      console.log(`   ${item.isDirectory ? '[dir] ' : '      '}${item.name}`)
    }

    // sprzątanie
    await client.remove(testName)
    console.log(`✅ Skasowano plik testowy: ${testName}`)
    console.log('🎉 TEST OK — FTPS działa, katalog i uprawnienia poprawne.')
  } catch (err) {
    console.error(`❌ TEST NIEUDANY: ${err.message}`)
    process.exit(1)
  } finally {
    client.close()
  }
}

main()
