<template>
  <span class="text-xs px-2 py-0.5 rounded-full font-medium" :class="cls">{{ label }}</span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { SourceStatus, ScanStatus } from '../types'

const props = defineProps<{ status: SourceStatus | ScanStatus }>()

const config: Record<string, { cls: string; label: string }> = {
  pending:          { cls: 'bg-slate-700 text-slate-400', label: 'oczekuje' },
  running:          { cls: 'bg-sky-900 text-sky-300', label: 'skanuje' },
  done:             { cls: 'bg-green-900 text-green-400', label: 'gotowe' },
  error:            { cls: 'bg-red-900 text-red-400', label: 'błąd' },
  no_data:          { cls: 'bg-slate-700 text-slate-500', label: 'brak danych' },
  captcha_required: { cls: 'bg-yellow-900 text-yellow-400', label: 'CAPTCHA' },
  captcha_timeout:  { cls: 'bg-orange-900 text-orange-400', label: 'timeout CAPTCHA' },
  completed:        { cls: 'bg-green-900 text-green-400', label: 'zakończony' },
  completed_with_errors: { cls: 'bg-yellow-900 text-yellow-400', label: 'zakończony (błędy)' },
  done_with_errors: { cls: 'bg-yellow-900 text-yellow-400', label: 'zakończony (błędy)' },
  failed:           { cls: 'bg-red-900 text-red-400', label: 'błąd' },
}

const cls = computed(() => config[props.status]?.cls ?? 'bg-slate-700 text-slate-400')
const label = computed(() => config[props.status]?.label ?? props.status)
</script>
