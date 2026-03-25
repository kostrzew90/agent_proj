import { ref, onUnmounted } from 'vue'
import { useScanStore } from '../stores/scan'
import type { WsMessage } from '../types'

export function useWebSocket(scanId: string) {
  const store = useScanStore()
  const connected = ref(false)
  let ws: WebSocket | null = null
  let retryTimer: ReturnType<typeof setTimeout> | null = null
  let retryDelay = 1000

  function connect() {
    const wsUrl = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/scan/${scanId}`
    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      connected.value = true
      retryDelay = 1000
    }

    ws.onmessage = (event) => {
      try {
        const msg: WsMessage = JSON.parse(event.data)
        store.handleWsMessage(msg)
      } catch {}
    }

    ws.onclose = () => {
      connected.value = false
      if (!store.scanComplete) {
        retryTimer = setTimeout(() => {
          retryDelay = Math.min(retryDelay * 2, 10000)
          connect()
        }, retryDelay)
      }
    }

    ws.onerror = () => {
      ws?.close()
    }
  }

  function sendCaptchaResponse(source: string, answer: string) {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'captcha_response', source, answer }))
    }
  }

  function disconnect() {
    if (retryTimer) clearTimeout(retryTimer)
    ws?.close()
    ws = null
  }

  onUnmounted(disconnect)

  return { connected, connect, disconnect, sendCaptchaResponse }
}
