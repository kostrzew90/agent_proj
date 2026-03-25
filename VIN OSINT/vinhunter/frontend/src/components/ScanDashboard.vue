<template>
  <div>
    <h2 class="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-3">
      Źródła danych
    </h2>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
      <SourceCard
        v-for="source in store.sourceList"
        :key="source.source"
        :source="source"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { useScanStore } from '../stores/scan'
import SourceCard from './SourceCard.vue'

const store = useScanStore()
</script>
