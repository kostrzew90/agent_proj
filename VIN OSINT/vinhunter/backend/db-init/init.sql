-- VINhunter Database Schema

-- Sesje skanowania
CREATE TABLE IF NOT EXISTS scans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vin VARCHAR(17) NOT NULL,
    plate VARCHAR(20),
    status VARCHAR(20) NOT NULL DEFAULT 'running',  -- running, completed, failed, completed_with_errors
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    decoded_data JSONB,          -- Zmergowane dane z VIN decode
    metadata JSONB               -- Dodatkowe info
);

CREATE INDEX IF NOT EXISTS idx_scans_vin ON scans(vin);
CREATE INDEX IF NOT EXISTS idx_scans_created ON scans(created_at DESC);

-- Wyniki poszczegolnych zrodel
CREATE TABLE IF NOT EXISTS scan_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_id UUID NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    source_name VARCHAR(50) NOT NULL,
    category VARCHAR(30) NOT NULL,
    status VARCHAR(20) NOT NULL,     -- done, error, no_data, captcha_timeout
    data JSONB,
    raw_html TEXT,
    screenshots TEXT[],
    error_message TEXT,
    execution_time_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_results_scan ON scan_results(scan_id);
CREATE INDEX IF NOT EXISTS idx_results_source ON scan_results(source_name);

-- Znalezione zdjecia
CREATE TABLE IF NOT EXISTS found_photos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_id UUID NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    source_name VARCHAR(50) NOT NULL,
    url TEXT NOT NULL,
    thumbnail_url TEXT,
    context TEXT,
    relevance_score FLOAT,
    downloaded BOOLEAN DEFAULT FALSE,
    local_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_photos_scan ON found_photos(scan_id);

-- Wygenerowane raporty
CREATE TABLE IF NOT EXISTS reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_id UUID NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    format VARCHAR(10) NOT NULL,    -- html_self, html_images
    file_path TEXT NOT NULL,
    file_size_bytes INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Konfiguracja pluginow
CREATE TABLE IF NOT EXISTS plugin_config (
    name VARCHAR(50) PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    settings JSONB DEFAULT '{}',
    last_used TIMESTAMPTZ,
    total_queries INTEGER DEFAULT 0,
    total_errors INTEGER DEFAULT 0
);
