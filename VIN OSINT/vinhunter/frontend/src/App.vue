<template>
  <div class="min-h-screen bg-slate-900">
    <!-- Navbar -->
    <nav class="border-b border-slate-800 bg-slate-950">
      <div class="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
        <router-link to="/" class="text-sky-400 font-bold text-lg tracking-tight">
          VINhunter
        </router-link>
        <div class="flex gap-4 text-sm">
          <router-link to="/" class="text-slate-400 hover:text-slate-200 transition-colors">Skanuj</router-link>
          <router-link to="/reports" class="text-slate-400 hover:text-slate-200 transition-colors">Raporty</router-link>
        </div>
      </div>
    </nav>

    <router-view />
  </div>
</template>
