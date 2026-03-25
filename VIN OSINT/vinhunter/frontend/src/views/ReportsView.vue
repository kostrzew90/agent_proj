<template>
  <div class="max-w-4xl mx-auto px-4 py-8">
    <h1 class="text-2xl font-bold text-sky-400 mb-6">Wygenerowane raporty</h1>

    <div v-if="!reports.length" class="text-center text-slate-500 mt-16">
      Brak raportów. Zakończ skan i kliknij "Generuj raport".
    </div>

    <div v-else class="space-y-3">
      <div
        v-for="report in reports"
        :key="report.id"
        class="bg-slate-800 rounded-lg px-4 py-3 flex items-center justify-between"
      >
        <div>
          <span class="font-mono font-semibold text-sky-400">{{ report.vin }}</span>
          <span v-if="report.plate" class="ml-2 text-slate-400 text-sm">{{ report.plate }}</span>
          <div class="text-slate-500 text-xs mt-0.5">
            {{ formatDate(report.created_at) }} · {{ formatSize(report.file_size_bytes) }} · {{ report.format }}
          </div>
        </div>
        <a
          :href="`/api/reports/${report.id}/download`"
          target="_blank"
          class="bg-sky-600 hover:bg-sky-500 text-white text-sm px-3 py-1.5 rounded transition-colors"
        >
          Pobierz
        </a>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { Report } from '../types'

const reports = ref<Report[]>([])

async function loadReports() {
  try {
    const res = await fetch('/api/reports')
    if (res.ok) reports.value = await res.json()
  } catch {}
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('pl-PL', { dateStyle: 'short', timeStyle: 'short' })
}

function formatSize(bytes: number) {
  if (!bytes) return '?'
  return bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`
}

onMounted(loadReports)
</script>
