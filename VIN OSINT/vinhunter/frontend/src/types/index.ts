export type ScanStatus = 'running' | 'completed' | 'completed_with_errors' | 'failed'

export type SourceStatus =
  | 'pending'
  | 'running'
  | 'done'
  | 'error'
  | 'no_data'
  | 'captcha_required'
  | 'captcha_timeout'

export type SourceCategory =
  | 'vin_decode'
  | 'registry'
  | 'damage'
  | 'photo_osint'
  | 'ads_archive'

export interface SourceState {
  source: string
  display_name: string
  status: SourceStatus
  data?: Record<string, unknown>
  error?: string
  execution_time_ms?: number
  captcha_image_base64?: string
  timeout_seconds?: number
}

export interface Scan {
  id: string
  vin: string
  plate?: string
  status: ScanStatus
  created_at: string
  completed_at?: string
  decoded_data?: Record<string, unknown>
}

export interface Photo {
  id: string
  source_name: string
  url: string
  thumbnail_url?: string
  context?: string
  relevance_score?: number
}

export interface Plugin {
  name: string
  display_name: string
  category: SourceCategory
  country: string
  enabled: boolean
  requires_captcha: boolean
  total_queries: number
  total_errors: number
  last_used?: string
}

export interface Report {
  id: string
  scan_id: string
  vin: string
  plate?: string
  format: string
  file_path: string
  file_size_bytes: number
  created_at: string
}

export interface WsMessage {
  type: 'source_update' | 'captcha_request' | 'scan_complete'
  source?: string
  display_name?: string
  status?: SourceStatus
  data?: Record<string, unknown>
  error?: string
  execution_time_ms?: number
  captcha_image_base64?: string
  timeout_seconds?: number
  total_sources?: number
  successful?: number
  errors?: number
  no_data?: number
}
