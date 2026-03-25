import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Scan, SourceState, Photo, WsMessage } from '../types'

export const useScanStore = defineStore('scan', () => {
  const currentScan = ref<Scan | null>(null)
  const sources = ref<Map<string, SourceState>>(new Map())
  const photos = ref<Photo[]>([])
  const scanComplete = ref(false)
  const scanSummary = ref<WsMessage | null>(null)
  const pendingCaptcha = ref<SourceState | null>(null)

  const sourceList = computed(() =>
    Array.from(sources.value.values()).sort((a, b) => {
      const order = { running: 0, captcha_required: 1, done: 2, error: 3, no_data: 4, pending: 5, captcha_timeout: 6 }
      return (order[a.status] ?? 9) - (order[b.status] ?? 9)
    })
  )

  const doneCount = computed(() =>
    Array.from(sources.value.values()).filter(s => s.status === 'done').length
  )
  const errorCount = computed(() =>
    Array.from(sources.value.values()).filter(s => s.status === 'error').length
  )
  const runningCount = computed(() =>
    Array.from(sources.value.values()).filter(s => s.status === 'running').length
  )

  function safeParse(val: unknown): Record<string, unknown> | undefined {
    if (!val) return undefined
    if (typeof val === 'object') return val as Record<string, unknown>
    if (typeof val === 'string') {
      try { return JSON.parse(val) } catch { return undefined }
    }
    return undefined
  }

  function handleWsMessage(msg: WsMessage) {
    if (msg.type === 'source_update' && msg.source) {
      const existing = sources.value.get(msg.source)
      sources.value.set(msg.source, {
        source: msg.source,
        display_name: msg.display_name || existing?.display_name || msg.source,
        status: msg.status || 'pending',
        data: safeParse(msg.data),
        error: msg.error,
        execution_time_ms: msg.execution_time_ms,
      })
    }

    if (msg.type === 'captcha_request' && msg.source) {
      const s = sources.value.get(msg.source)
      pendingCaptcha.value = {
        source: msg.source,
        display_name: s?.display_name || msg.source,
        status: 'captcha_required',
        captcha_image_base64: msg.captcha_image_base64,
        timeout_seconds: msg.timeout_seconds,
      }
    }

    if (msg.type === 'scan_complete') {
      scanComplete.value = true
      scanSummary.value = msg
    }
  }

  function resetForScan(scan: Scan) {
    currentScan.value = scan
    sources.value = new Map()
    photos.value = []
    scanComplete.value = false
    scanSummary.value = null
    pendingCaptcha.value = null
  }

  function clearCaptcha() {
    pendingCaptcha.value = null
  }

  return {
    currentScan, sources, sourceList, photos,
    scanComplete, scanSummary, pendingCaptcha,
    doneCount, errorCount, runningCount,
    handleWsMessage, resetForScan, clearCaptcha,
  }
})
