<template>
  <div
    class="bg-slate-800 rounded-lg p-4 transition-all overflow-hidden"
    :class="{ 'ring-1 ring-yellow-500': source.status === 'captcha_required' }"
  >
    <!-- Header -->
    <div class="flex items-center justify-between mb-1">
      <div class="flex items-center gap-2">
        <span class="text-lg">{{ statusIcon }}</span>
        <span class="font-medium text-sm">{{ source.display_name }}</span>
      </div>
      <div class="flex items-center gap-2">
        <span v-if="source.execution_time_ms" class="text-xs text-slate-600">{{ source.execution_time_ms }}ms</span>
        <StatusBadge :status="source.status" />
      </div>
    </div>

    <!-- Error -->
    <div v-if="source.status === 'error'" class="mt-1 text-xs text-red-400">
      {{ source.error }}
    </div>

    <!-- Running animation -->
    <div v-if="source.status === 'running'" class="mt-2 flex items-center gap-2">
      <div class="flex gap-0.5">
        <div class="w-1.5 h-1.5 rounded-full bg-sky-400 animate-bounce" style="animation-delay:0ms" />
        <div class="w-1.5 h-1.5 rounded-full bg-sky-400 animate-bounce" style="animation-delay:150ms" />
        <div class="w-1.5 h-1.5 rounded-full bg-sky-400 animate-bounce" style="animation-delay:300ms" />
      </div>
    </div>

    <!-- Results -->
    <div v-if="source.status === 'done' && source.data" class="mt-2">
      <button
        @click="expanded = !expanded"
        class="text-xs text-sky-400 hover:text-sky-300 transition-colors"
      >
        {{ expanded ? 'Zwi\u0144' : summaryText }}
      </button>

      <div v-if="expanded" class="mt-2 overflow-hidden">
        <!-- NHTSA Recalls -->
        <template v-if="source.source === 'nhtsa_recalls' && source.data.recalls">
          <div class="space-y-2">
            <div class="text-xs text-slate-400 mb-1">Znaleziono {{ source.data.total_recalls }} recall(i)</div>
            <div
              v-for="(recall, i) in (source.data.recalls as any[])"
              :key="i"
              class="bg-slate-900 rounded p-3 space-y-1"
            >
              <div class="text-xs font-medium text-amber-400">{{ recall.component }}</div>
              <div class="text-xs text-slate-400">{{ recall.report_date }} &middot; {{ recall.campaign_number }}</div>
              <div class="text-xs text-slate-300 leading-relaxed">{{ recall.summary?.slice(0, 200) }}{{ recall.summary?.length > 200 ? '...' : '' }}</div>
              <div v-if="recall.consequence" class="text-xs text-red-400/80">{{ recall.consequence?.slice(0, 150) }}{{ recall.consequence?.length > 150 ? '...' : '' }}</div>
            </div>
          </div>
        </template>

        <!-- NHTSA Complaints -->
        <template v-else-if="source.source === 'nhtsa_complaints' && source.data.by_component">
          <div class="space-y-1.5">
            <div class="text-xs text-slate-400 mb-1">
              {{ source.data.total_complaints }} skarg, {{ source.data.total_crashes }} wypadk(i/&oacute;w)
            </div>
            <div
              v-for="(comp, i) in (source.data.by_component as any[])"
              :key="i"
              class="bg-slate-900 rounded p-2 flex items-center justify-between gap-2"
            >
              <span class="text-xs text-slate-300 truncate">{{ comp.component }}</span>
              <div class="flex items-center gap-3 shrink-0">
                <span class="text-xs text-slate-400">{{ comp.count }}</span>
                <span v-if="comp.crashes > 0" class="text-xs text-red-400">{{ comp.crashes }} crash</span>
              </div>
            </div>
          </div>
        </template>

        <!-- EU Recalls (car-recalls.eu) -->
        <template v-else-if="source.source === 'car_recalls_eu' && source.data.recalls">
          <div class="space-y-2">
            <div class="text-xs text-slate-400 mb-1">Znaleziono {{ source.data.total_recalls }} recall(i) EU</div>
            <div
              v-for="(recall, i) in (source.data.recalls as any[])"
              :key="i"
              class="bg-slate-900 rounded p-3 space-y-1"
            >
              <a
                :href="recall.url"
                target="_blank"
                class="text-xs font-medium text-sky-400 hover:text-sky-300 block leading-snug"
              >{{ recall.title }}</a>
              <div v-if="recall.excerpt" class="text-xs text-slate-300 leading-relaxed">{{ recall.excerpt }}</div>
            </div>
          </div>
        </template>

        <!-- NICB VINCheck -->
        <template v-else-if="source.source === 'nicb_vincheck'">
          <div class="bg-slate-900 rounded p-3 flex items-center gap-3">
            <span class="text-2xl">{{ nicbIcon }}</span>
            <div>
              <div class="text-sm font-medium" :class="nicbColor">{{ nicbLabel }}</div>
              <div class="text-xs text-slate-400">{{ source.data.description }}</div>
            </div>
          </div>
        </template>

        <!-- KBA Recalls (Germany) -->
        <template v-else-if="source.source === 'kba_recalls' && source.data.recalls">
          <div class="space-y-2">
            <div class="text-xs text-slate-400 mb-1">Znaleziono {{ source.data.total_recalls }} recall(i) KBA</div>
            <div
              v-for="(recall, i) in (source.data.recalls as any[])"
              :key="i"
              class="bg-slate-900 rounded p-3 space-y-1"
            >
              <div v-if="recall.kba_ref" class="text-xs font-medium text-amber-400">{{ recall.kba_ref }}</div>
              <div v-if="recall.defect" class="text-xs text-slate-300 leading-relaxed">{{ recall.defect }}</div>
              <div class="flex gap-3 text-xs text-slate-500">
                <span v-if="recall.publication_date">{{ recall.publication_date }}</span>
                <span v-if="recall.production_period">Produkcja: {{ recall.production_period }}</span>
                <span v-if="recall.manufacturer_code">Kod: {{ recall.manufacturer_code }}</span>
              </div>
            </div>
          </div>
        </template>

        <!-- NHTSA Safety Ratings -->
        <template v-else-if="source.source === 'nhtsa_safety'">
          <div class="grid grid-cols-2 gap-2">
            <div v-for="(val, key) in safetyFields" :key="key" class="bg-slate-900 rounded p-2">
              <div class="text-xs text-slate-500">{{ key }}</div>
              <div class="text-sm font-medium" :class="ratingColor(val)">{{ formatRating(val) }}</div>
            </div>
          </div>
        </template>

        <!-- Generic flat data (nhtsa decode, vininfo_local, etc.) -->
        <template v-else>
          <div class="space-y-0.5 max-h-80 overflow-y-auto">
            <div
              v-for="(val, key) in flatData"
              :key="key"
              class="flex gap-2 text-xs"
            >
              <span class="text-slate-500 min-w-32 shrink-0">{{ formatKey(String(key)) }}</span>
              <span class="text-slate-200 break-words min-w-0">{{ formatVal(val) }}</span>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { SourceState } from '../types'
import StatusBadge from './StatusBadge.vue'

const props = defineProps<{ source: SourceState }>()
const expanded = ref(false)

const statusIcon = computed(() => {
  const map: Record<string, string> = {
    pending: '\u23F3', running: '\uD83D\uDD04', done: '\u2705', error: '\u274C',
    no_data: '\u26AA', captcha_required: '\uD83D\uDD11', captcha_timeout: '\u23F1\uFE0F',
  }
  return map[props.source.status] ?? '\u2753'
})

// NICB VINCheck display helpers
const nicbIcon = computed(() => {
  const s = props.source.data?.status
  if (s === 'clean') return '\u2705'
  if (s === 'stolen') return '\uD83D\uDEA8'
  if (s === 'salvage') return '\u26A0\uFE0F'
  return '\u2753'
})
const nicbColor = computed(() => {
  const s = props.source.data?.status
  if (s === 'clean') return 'text-green-400'
  if (s === 'stolen') return 'text-red-400'
  if (s === 'salvage') return 'text-amber-400'
  return 'text-slate-400'
})
const nicbLabel = computed(() => {
  const s = props.source.data?.status
  if (s === 'clean') return 'Clean — no records'
  if (s === 'stolen') return 'STOLEN — active theft record'
  if (s === 'salvage') return 'SALVAGE — total loss record'
  return 'Unknown'
})

const summaryText = computed(() => {
  const d = props.source.data
  if (!d) return 'Poka\u017C wyniki'
  const src = props.source.source

  if (src === 'nhtsa_recalls' && d.total_recalls != null)
    return `Poka\u017C ${d.total_recalls} recall(i)`
  if (src === 'nhtsa_complaints' && d.total_complaints != null)
    return `Poka\u017C ${d.total_complaints} skarg`
  if (src === 'nhtsa_safety')
    return `Poka\u017C oceny bezpiecze\u0144stwa`
  if (src === 'nhtsa')
    return `Poka\u017C dane pojazdu`
  if (src === 'car_recalls_eu' && d.total_recalls != null)
    return `Poka\u017C ${d.total_recalls} recall(i) EU`
  if (src === 'nicb_vincheck' && d.status)
    return `Status: ${d.status}`
  if (src === 'kba_recalls' && d.total_recalls != null)
    return `Poka\u017C ${d.total_recalls} recall(i) KBA`

  const count = Object.keys(d).length
  return `Poka\u017C wyniki (${count})`
})

// Safety ratings fields
const safetyFields = computed(() => {
  const d = props.source.data
  if (!d) return {}
  const keys = [
    'overall_rating', 'frontal_crash_rating', 'side_crash_rating',
    'rollover_rating', 'rollover_probability',
    'nhtsa_electronic_stability_control',
    'nhtsa_forward_collision_warning', 'nhtsa_lane_departure_warning',
  ]
  const labels: Record<string, string> = {
    overall_rating: 'Overall',
    frontal_crash_rating: 'Frontal crash',
    side_crash_rating: 'Side crash',
    rollover_rating: 'Rollover',
    rollover_probability: 'Rollover probability',
    nhtsa_electronic_stability_control: 'ESC',
    nhtsa_forward_collision_warning: 'FCW',
    nhtsa_lane_departure_warning: 'LDW',
  }
  const result: Record<string, unknown> = {}
  for (const k of keys) {
    if (d[k] != null) result[labels[k] || k] = d[k]
  }
  return result
})

// Flat data for generic display — exclude arrays/objects
const flatData = computed(() => {
  const d = props.source.data
  if (!d) return {}
  const excluded = new Set(['raw_html', 'mot_tests', 'recalls', 'by_component', 'all_variants', 'sample_descriptions'])
  return Object.fromEntries(
    Object.entries(d).filter(([k, v]) => {
      if (excluded.has(k)) return false
      if (Array.isArray(v)) return false
      if (typeof v === 'object' && v !== null) return false
      return v != null && v !== ''
    })
  )
})

function formatKey(key: string): string {
  return key.replace(/_/g, ' ')
}

function formatVal(val: unknown): string {
  if (val == null) return '-'
  return String(val).slice(0, 120)
}

function formatRating(val: unknown): string {
  if (val == null) return '-'
  const s = String(val)
  if (s === 'Not Rated') return 'N/R'
  if (typeof val === 'number' && val < 1) return `${(val * 100).toFixed(1)}%`
  const num = Number(s)
  if (!isNaN(num) && num >= 1 && num <= 5) return '\u2605'.repeat(num) + '\u2606'.repeat(5 - num)
  return s
}

function ratingColor(val: unknown): string {
  const s = String(val)
  if (s === 'Not Rated') return 'text-slate-500'
  if (s === 'Standard' || s === 'Yes') return 'text-green-400'
  if (s === 'No') return 'text-slate-500'
  const num = Number(s)
  if (!isNaN(num) && num >= 1 && num <= 5) {
    if (num >= 4) return 'text-green-400'
    if (num >= 3) return 'text-yellow-400'
    return 'text-red-400'
  }
  if (typeof val === 'number' && val < 1) {
    return val < 0.15 ? 'text-green-400' : 'text-yellow-400'
  }
  return 'text-slate-200'
}
</script>
