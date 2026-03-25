<template>
  <div class="max-w-6xl mx-auto px-4 py-8">
    <div v-if="!store.currentScan" class="text-center text-slate-500 mt-20">Ładowanie...</div>

    <template v-else>
      <!-- Header -->
      <div class="flex items-center justify-between mb-6">
        <div>
          <h1 class="text-2xl font-bold font-mono text-sky-400">{{ store.currentScan.vin }}</h1>
          <p v-if="store.currentScan.plate" class="text-slate-400 text-sm mt-0.5">Tablica: {{ store.currentScan.plate }}</p>
        </div>
        <div class="flex items-center gap-3">
          <span class="text-sm text-slate-500">
            {{ store.doneCount }} / {{ store.sourceList.length }} źródeł
          </span>
          <div v-if="!store.scanComplete" class="w-3 h-3 rounded-full bg-sky-400 animate-pulse" />
          <div v-else class="w-3 h-3 rounded-full bg-green-500" />
        </div>
      </div>

      <!-- VIN Decoded -->
      <VinDecoded v-if="store.currentScan.decoded_data" :data="store.currentScan.decoded_data" class="mb-6" />

      <!-- CAPTCHA Dialog -->
      <CaptchaDialog
        v-if="store.pendingCaptcha"
        :source-state="store.pendingCaptcha"
        @submit="onCaptchaSubmit"
        @skip="onCaptchaSkip"
      />

      <!-- Dashboard źródeł -->
      <ScanDashboard />

      <!-- Zdjęcia -->
      <PhotoGallery v-if="store.photos.length" :photos="store.photos" class="mt-6" />

      <!-- Export -->
      <ReportExport v-if="store.scanComplete" :scan-id="store.currentScan.id" class="mt-6" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useScanStore } from '../stores/scan'
import { useWebSocket } from '../composables/useWebSocket'
import VinDecoded from '../components/VinDecoded.vue'
import ScanDashboard from '../components/ScanDashboard.vue'
import CaptchaDialog from '../components/CaptchaDialog.vue'
import PhotoGallery from '../components/PhotoGallery.vue'
import ReportExport from '../components/ReportExport.vue'

const route = useRoute()
const store = useScanStore()
const scanId = route.params.id as string
const { connect, sendCaptchaResponse } = useWebSocket(scanId)

function safeParse(val: unknown): Record<string, unknown> | undefined {
  if (!val) return undefined
  if (typeof val === 'object') return val as Record<string, unknown>
  if (typeof val === 'string') {
    try { return JSON.parse(val) } catch { return undefined }
  }
  return undefined
}

async function loadScan() {
  const res = await fetch(`/api/scan/${scanId}`)
  if (res.ok) {
    const scan = await res.json()
    // Parse decoded_data if it's a JSON string
    scan.decoded_data = safeParse(scan.decoded_data)
    store.resetForScan(scan)

    // Jeśli skan już skończony — załaduj wyniki z API
    if (scan.status !== 'running') {
      const r = await fetch(`/api/scan/${scanId}/results`)
      if (r.ok) {
        const { results, photos } = await r.json()
        store.photos = photos
        for (const result of results) {
          store.sources.set(result.source_name, {
            source: result.source_name,
            display_name: result.source_name,
            status: result.status,
            data: safeParse(result.data),
            error: result.error_message,
            execution_time_ms: result.execution_time_ms,
          })
        }
        store.scanComplete = true
      }
    }
  }
}

function onCaptchaSubmit(source: string, answer: string) {
  sendCaptchaResponse(source, answer)
  store.clearCaptcha()
}

function onCaptchaSkip() {
  store.clearCaptcha()
}

onMounted(async () => {
  await loadScan()
  connect()
})
</script>
