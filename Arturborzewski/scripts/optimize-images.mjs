import sharp from 'sharp'
import { readdir, stat } from 'fs/promises'
import { join, extname, basename, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const IMAGES_DIR = join(__dirname, '../public/images')
const SIZES = {
  'hero-lawyer': 1920,
  'mecenas-artur': 1200,
  'default': 800,
}

async function getFiles(dir) {
  const entries = await readdir(dir, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) {
      files.push(...await getFiles(full))
    } else if (['.jpg', '.jpeg', '.png'].includes(extname(entry.name).toLowerCase())) {
      files.push(full)
    }
  }
  return files
}

async function optimize(file) {
  const ext = extname(file)
  const name = basename(file, ext)
  const webpPath = file.replace(ext, '.webp')

  // Don't overwrite existing WebP if original is not newer
  try {
    const [origStat, webpStat] = await Promise.all([stat(file), stat(webpPath)])
    if (webpStat.mtimeMs > origStat.mtimeMs) return
  } catch {
    // WebP doesn't exist — continue
  }

  const width = Object.entries(SIZES).find(([key]) => name.includes(key))?.[1] ?? SIZES.default
  await sharp(file).resize(width, null, { withoutEnlargement: true }).webp({ quality: 85 }).toFile(webpPath)
  console.log(`✓ ${name}${ext} → ${name}.webp (max ${width}px)`)
}

async function main() {
  let files
  try {
    files = await getFiles(IMAGES_DIR)
  } catch {
    console.log('ℹ️  Brak folderu public/images — pomijam optymalizację')
    return
  }

  if (files.length === 0) {
    console.log('ℹ️  Brak obrazów do optymalizacji')
    return
  }

  await Promise.all(files.map(optimize))
  console.log(`✅ Optymalizacja zakończona (${files.length} plików)`)
}

main().catch(console.error)
