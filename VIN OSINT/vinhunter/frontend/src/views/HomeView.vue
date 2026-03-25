<template>
  <div class="max-w-2xl mx-auto px-4 py-16">
    <div class="text-center mb-10">
      <h1 class="text-4xl font-bold text-sky-400 mb-3">VINhunter</h1>
      <p class="text-slate-400">OSINT dla kupujących używane auta z Europy</p>
    </div>

    <VinInput @scan-started="onScanStarted" />

    <!-- Ostatnie skany -->
    <div v-if="recentScans.length" class="mt-10">
      <h2 class="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-3">Ostatnie skany</h2>
      <div class="space-y-2">
        <router-link
          v-for="scan in recentScans"
          :key="scan.id"
          :to="`/scan/${scan.id}`"
          class="flex items-center justify-between bg-slate-800 hover:bg-slate-700 rounded-lg px-4 py-3 transition-colors"
        >
          <div>
            <span class="font-mono font-semibold text-sky-400">{{ scan.vin }}</span>
            <span v-if="scan.plate" class="ml-2 text-slate-400 text-sm">{{ scan.plate }}</span>
          </div>
          <div class="flex items-center gap-3">
            <StatusBadge :status="scan.status" />
            <span class="text-slate-500 text-xs">{{ formatDate(scan.created_at) }}</span>
          </div>
        </router-link>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import VinInput from '../components/VinInput.vue'
import StatusBadge from '../components/StatusBadge.vue'
import type { Scan } from '../types'

const router = useRouter()
const recentScans = ref<Scan[]>([])

async function loadRecentScans() {
  try {
    const res = await fetch('/api/scans')
    if (res.ok) recentScans.value = await res.json()
  } catch {}
}

function onScanStarted(scanId: string) {
  router.push(`/scan/${scanId}`)
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('pl-PL', { dateStyle: 'short', timeStyle: 'short' })
}

onMounted(loadRecentScans)
</script>
