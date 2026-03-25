<template>
  <div class="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
    <div class="bg-slate-800 rounded-xl p-6 max-w-sm w-full shadow-2xl">
      <h3 class="text-lg font-semibold text-yellow-400 mb-1 flex items-center gap-2">
        🔑 CAPTCHA wymagana
      </h3>
      <p class="text-slate-400 text-sm mb-4">
        Źródło <strong class="text-slate-200">{{ sourceState.display_name }}</strong> wymaga weryfikacji.
        Czas: <strong :class="timeLeft < 30 ? 'text-red-400' : 'text-slate-200'">{{ timeLeft }}s</strong>
      </p>

      <div v-if="sourceState.captcha_image_base64" class="mb-4 bg-white rounded-lg p-2 flex justify-center">
        <img :src="sourceState.captcha_image_base64" alt="CAPTCHA" class="max-h-24 object-contain" />
      </div>

      <input
        v-model="answer"
        ref="inputRef"
        type="text"
        placeholder="Wpisz tekst z obrazka..."
        class="w-full bg-slate-900 border border-slate-600 rounded-lg px-4 py-2.5 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-yellow-500 mb-4"
        @keyup.enter="submit"
      />

      <div class="flex gap-2">
        <button
          @click="submit"
          :disabled="!answer.trim()"
          class="flex-1 bg-yellow-600 hover:bg-yellow-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-semibold py-2 rounded-lg transition-colors"
        >
          Wyślij
        </button>
        <button
          @click="$emit('skip')"
          class="px-4 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-lg transition-colors text-sm"
        >
          Pomiń
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import type { SourceState } from '../types'

const props = defineProps<{ sourceState: SourceState }>()
const emit = defineEmits<{
  submit: [source: string, answer: string]
  skip: []
}>()

const answer = ref('')
const inputRef = ref<HTMLInputElement>()
const timeLeft = ref(props.sourceState.timeout_seconds ?? 120)

let timer: ReturnType<typeof setInterval>

onMounted(() => {
  inputRef.value?.focus()
  timer = setInterval(() => {
    timeLeft.value--
    if (timeLeft.value <= 0) {
      clearInterval(timer)
      emit('skip')
    }
  }, 1000)
})

onUnmounted(() => clearInterval(timer))

function submit() {
  if (!answer.value.trim()) return
  emit('submit', props.sourceState.source, answer.value.trim())
}
</script>
