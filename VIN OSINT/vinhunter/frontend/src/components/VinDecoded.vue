<template>
  <div class="bg-slate-800 rounded-xl p-5">
    <h2 class="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-3">Dane pojazdu</h2>
    <div v-if="Object.keys(filteredData).length" class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
      <div
        v-for="(val, key) in filteredData"
        :key="key"
        class="bg-slate-900 rounded-lg p-3"
      >
        <div class="text-xs text-slate-500 uppercase tracking-wide mb-1">
          {{ formatKey(String(key)) }}
        </div>
        <div class="text-sm font-medium text-slate-100 break-words">{{ formatVal(val) }}</div>
      </div>
    </div>
    <div v-else class="text-sm text-slate-500">Brak danych dekodowania</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ data: Record<string, unknown> | string }>()

const parsedData = computed(() => {
  if (!props.data) return {}
  if (typeof props.data === 'string') {
    try { return JSON.parse(props.data) } catch { return {} }
  }
  return props.data
})

const filteredData = computed(() => {
  const excluded = new Set([
    'vin', 'wmi', 'vds', 'vis', 'error_code', 'error_text',
    'raw_html', 'mot_tests', 'recalls', 'by_component', 'all_variants',
  ])
  return Object.fromEntries(
    Object.entries(parsedData.value).filter(([k, v]) => {
      if (excluded.has(k)) return false
      if (v == null || v === '' || v === 'null') return false
      if (Array.isArray(v) || (typeof v === 'object' && v !== null)) return false
      return true
    })
  )
})

function formatKey(key: string): string {
  return key.replace(/_/g, ' ')
}

function formatVal(val: unknown): string {
  if (val == null) return '-'
  return String(val)
}
</script>
