<template>
  <div class="bg-slate-800 rounded-xl p-5">
    <h2 class="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-3">Eksport raportu</h2>

    <div class="flex items-center gap-3">
      <button
        @click="generate('html_self')"
        :disabled="loading"
        class="bg-sky-600 hover:bg-sky-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-semibold px-5 py-2.5 rounded-lg transition-colors flex items-center gap-2"
      >
        <svg v-if="loading" class="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
        </svg>
        {{ loading ? 'Generuję...' : 'Generuj raport HTML' }}
      </button>

      <span class="text-slate-500 text-sm">Self-contained (jeden plik)</span>
    </div>

    <div v-if="reportId" class="mt-3">
      <a
        :href="`/api/reports/${reportId}/download`"
        target="_blank"
        class="text-sky-400 hover:text-sky-300 text-sm transition-colors"
      >
        ↓ Pobierz wygenerowany raport
      </a>
    </div>

    <div v-if="error" class="mt-2 text-red-400 text-sm">{{ error }}</div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ scanId: string }>()
const loading = ref(false)
const reportId = ref('')
const error = ref('')

async function generate(format: string) {
  loading.value = true
  error.value = ''
  try {
    const res = await fetch(`/api/reports/${props.scanId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ format }),
    })
    if (!res.ok) throw new Error('Błąd generowania raportu')
    const data = await res.json()
    reportId.value = data.report_id
  } catch (e) {
    error.value = String(e)
  } finally {
    loading.value = false
  }
}
</script>
