import { Client } from 'basic-ftp'
import { existsSync } from 'fs'
import { readdir, stat } from 'fs/promises'
import { join, dirname, basename, relative } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = join(__dirname, '..')
const LOCAL_OUT = join(PROJECT_ROOT, 'out')

const RECONNECT_DELAY_MS = 1000
const MAX_ATTEMPTS_PER_FILE = 5
const FILES_PER_SESSION = 8

function readConfig() {
  const required = ['FTP_HOST', 'FTP_USER', 'FTP_PASSWORD']
  const missing = required.filter((key) => !process.env[key])
  if (missing.length > 0) {
    console.error(`❌ Brakuje zmiennych środowiskowych: ${missing.join(', ')}`)
    process.exit(1)
  }

  return {
    host: process.env.FTP_HOST,
    user: process.env.FTP_USER,
    password: process.env.FTP_PASSWORD,
    port: Number(process.env.FTP_PORT ?? 21),
    secure: (process.env.FTP_SECURE ?? 'true') !== 'false',
    remoteDir: process.env.FTP_REMOTE_DIR ?? '/public_html',
  }
}

// Rekurencyjnie zbiera pliki z lokalnego katalogu jako listę { localPath, relPath }.
// relPath zawsze z ukośnikami "/" (POSIX), niezależnie od platformy.
async function collectFiles(dir, baseDir) {
  const entries = await readdir(dir, { withFileTypes: true })
  const files = []

  for (const entry of entries) {
    const fullPath = join(dir, entry.name)
    if (entry.isDirectory()) {
      files.push(...(await collectFiles(fullPath, baseDir)))
    } else if (entry.isFile()) {
      const relPath = relative(baseDir, fullPath).split('\\').join('/')
      files.push({ localPath: fullPath, relPath })
    }
  }

  return files
}

// Katalog zdalny dla danego pliku (bez trailing slash, "/" jako separator).
function remoteDirFor(remoteRoot, relPath) {
  const dir = dirname(relPath)
  if (dir === '.') return remoteRoot
  return `${remoteRoot}/${dir}`
}

async function connect(config) {
  const client = new Client(30000)
  client.ftp.verbose = false
  await client.access({
    host: config.host,
    port: config.port,
    user: config.user,
    password: config.password,
    secure: config.secure,
    // home.pl potrafi serwować FTPS z certyfikatem self-signed / niepasującym
    // do hostname — bez tego basic-ftp odrzuci połączenie mimo poprawnych danych.
    secureOptions: config.secure ? { rejectUnauthorized: false } : undefined,
  })
  return client
}

async function main() {
  if (!existsSync(LOCAL_OUT)) {
    console.error('❌ Katalog out/ nie istnieje — uruchom najpierw: npm run build')
    process.exit(1)
  }

  const config = readConfig()
  const allFiles = (await collectFiles(LOCAL_OUT, LOCAL_OUT)).sort((a, b) =>
    a.relPath.localeCompare(b.relPath)
  )

  // home.pl zrywa połączenie FTPS przy STOR pliku o rozmiarze 0 bajtów —
  // takie pliki (np. .gitkeep) nie mają znaczenia na serwerze, więc pomijamy je.
  const files = []
  const skipped = []
  for (const file of allFiles) {
    const { size } = await stat(file.localPath)
    if (size === 0) {
      skipped.push(file.relPath)
    } else {
      files.push(file)
    }
  }
  const total = files.length

  if (skipped.length > 0) {
    console.log(`ℹ️  Pomijam ${skipped.length} pustych plików (bez znaczenia na serwerze): ${skipped.join(', ')}`)
  }

  console.log(`ℹ️  Łączenie z ${config.host}:${config.port}...`)
  let client = await connect(config)
  let currentRemoteDir = null
  let uploadedSinceReconnect = 0

  try {
    console.log(`ℹ️  Wgrywanie ${total} plików do ${config.host}:${config.remoteDir}...`)

    for (let i = 0; i < total; i++) {
      const { localPath, relPath } = files[i]
      const targetDir = remoteDirFor(config.remoteDir, relPath)
      let attempts = 0
      let lastError = null
      let uploaded = false

      while (!uploaded) {
        attempts++
        try {
          if (targetDir !== currentRemoteDir) {
            await client.ensureDir(targetDir)
            currentRemoteDir = targetDir
          }
          await client.uploadFrom(localPath, basename(relPath))
          console.log(`  ↑ ${relPath}`)
          uploaded = true
          uploadedSinceReconnect++
        } catch (err) {
          lastError = err
          if (attempts >= MAX_ATTEMPTS_PER_FILE) {
            throw new Error(
              `Nie udało się wgrać ${relPath} po ${MAX_ATTEMPTS_PER_FILE} próbach: ${lastError.message}`
            )
          }
          console.log(`  ⟳ reconnect (plik ${i + 1}/${total})...`)
          client.close()
          await new Promise((resolve) => setTimeout(resolve, RECONNECT_DELAY_MS))
          client = await connect(config)
          currentRemoteDir = null
          uploadedSinceReconnect = 0
        }
      }

      // home.pl zrywa sesję FTPS po kilku-kilkunastu plikach — proaktywny
      // reconnect co FILES_PER_SESSION plików chroni przed zerwaniem w trakcie wysyłki.
      if (uploaded && uploadedSinceReconnect >= FILES_PER_SESSION && i < total - 1) {
        console.log('  ⟳ reconnect (limit sesji)...')
        client.close()
        await new Promise((resolve) => setTimeout(resolve, RECONNECT_DELAY_MS))
        client = await connect(config)
        currentRemoteDir = null
        uploadedSinceReconnect = 0
      }
    }

    console.log(`✅ Wgrano ${total} plików na ${config.host}:${config.remoteDir}`)
  } catch (err) {
    console.error(`❌ Błąd deployu: ${err.message}`)
    process.exit(1)
  } finally {
    client.close()
  }
}

main()
