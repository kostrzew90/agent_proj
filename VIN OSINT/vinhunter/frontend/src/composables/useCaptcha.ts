import { ref } from 'vue'

export function useCaptcha() {
  const answer = ref('')
  const submitting = ref(false)

  function reset() {
    answer.value = ''
    submitting.value = false
  }

  return { answer, submitting, reset }
}
