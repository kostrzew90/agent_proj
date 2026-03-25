<template>
  <div class="bg-slate-800 rounded-xl p-6">
    <form @submit.prevent="submit">
      <div class="mb-4">
        <label class="block text-sm font-medium text-slate-400 mb-2">Numer VIN</label>
        <input
          v-model="vin"
          type="text"
          maxlength="17"
          placeholder="np. WBADE6302V1234567"
          class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-3 font-mono text-lg text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-transparent transition-all uppercase"
          :class="{ 'border-red-500 focus:ring-red-500': error }"
          @input="onInput"
        />
        <div v-if="vin.length > 0" class="flex items-center gap-2 mt-1.5">
          <div
            class="h-1 rounded-full flex-1 transition-all"
            :class="{
              'bg-red-500': vin.length < 17,
              'bg-yellow-500': vin.length === 17 && error,
              'bg-green-500': vin.length === 17 && !error,
            }"
          />
          <span class="text-xs text-slate-500">{{ vin.length }}/17</span>
        </div>
        <p v-if="error" class="text-red-400 text-sm mt-1.5">{{ error }}</p>
      </div>

      <div class="mb-5">
        <label class="block text-sm font-medium text-slate-400 mb-2">
          Tablica rejestracyjna
          <span class="text-slate-600 font-normal">(opcjonalnie)</span>
        </label>
        <input
          v-model="plate"
          type="text"
          placeholder="np. WA12345, AB CD 123"
          class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 font-mono text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-transparent transition-all uppercase"
        />
      </div>

      <button
        type="submit"
        :disabled="loading || !!error || vin.length !== 17"
        class="w-full bg-sky-600 hover:bg-sky-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-semibold py-3 rounded-lg transition-colors flex items-center justify-center gap-2"
      >
        <svg v-if="loading" class="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
        </svg>
        {{ loading ? 'Uruchamiam skan...' : 'Skanuj' }}
      </button>
    </form>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const emit = defineEmits<{ 'scan-started': [scanId: string] }>()

const vin = ref('')
const plate = ref('')
const error = ref('')
const loading = ref(false)

// Znaki niedozwolone w VIN
const INVALID_CHARS = /[IOQ]/i

function onInput() {
  error.value = ''
  const v = vin.value.toUpperCase()
  vin.value = v

  if (v.length === 17) {
    if (INVALID_CHARS.test(v)) {
      error.value = 'VIN nie może zawierać liter I, O, Q'
    }
  }
}

async function submit() {
  if (loading.value || error.value || vin.value.length !== 17) return

  loading.value = true
  try {
    const res = await fetch('/api/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        vin: vin.value.toUpperCase(),
        plate: plate.value.toUpperCase() || undefined,
      }),
    })

    if (!res.ok) {
      const data = await res.json()
      error.value = data.detail || 'Błąd serwera'
      return
    }

    const { scan_id } = await res.json()
    emit('scan-started', scan_id)
  } catch (e) {
    error.value = 'Nie można połączyć się z serwerem'
  } finally {
    loading.value = false
  }
}
</script>
