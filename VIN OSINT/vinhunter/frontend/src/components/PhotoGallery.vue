<template>
  <div>
    <h2 class="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-3">
      Znalezione zdjęcia ({{ photos.length }})
    </h2>
    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
      <a
        v-for="photo in photos"
        :key="photo.id"
        :href="photo.url"
        target="_blank"
        class="group bg-slate-800 rounded-lg overflow-hidden hover:ring-2 hover:ring-sky-500 transition-all"
      >
        <div class="aspect-video bg-slate-700 overflow-hidden">
          <img
            :src="photo.thumbnail_url || photo.url"
            :alt="photo.context || photo.source_name"
            class="w-full h-full object-cover group-hover:scale-105 transition-transform"
            loading="lazy"
            @error="(e) => (e.target as HTMLImageElement).style.display = 'none'"
          />
        </div>
        <div class="p-2">
          <div class="text-xs text-slate-400 truncate">{{ photo.source_name }}</div>
          <div v-if="photo.context" class="text-xs text-slate-500 truncate">{{ photo.context }}</div>
        </div>
      </a>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Photo } from '../types'
defineProps<{ photos: Photo[] }>()
</script>
