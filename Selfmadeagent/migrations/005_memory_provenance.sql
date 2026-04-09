-- 005_memory_provenance.sql — Provenance, review, verification columns

-- learned_patterns
ALTER TABLE learned_patterns ADD COLUMN IF NOT EXISTS needs_review BOOLEAN DEFAULT FALSE;
ALTER TABLE learned_patterns ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;
ALTER TABLE learned_patterns ADD COLUMN IF NOT EXISTS review_result TEXT;
ALTER TABLE learned_patterns ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'reflection';
ALTER TABLE learned_patterns ADD COLUMN IF NOT EXISTS source_session UUID;
ALTER TABLE learned_patterns ADD COLUMN IF NOT EXISTS verified BOOLEAN DEFAULT FALSE;
ALTER TABLE learned_patterns ADD COLUMN IF NOT EXISTS verified_by TEXT;
ALTER TABLE learned_patterns ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;
ALTER TABLE learned_patterns ADD COLUMN IF NOT EXISTS times_failed INT DEFAULT 0;

-- episodes
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'agent';
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS verified BOOLEAN DEFAULT FALSE;
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS verified_by TEXT;

-- project_memory
ALTER TABLE project_memory ADD COLUMN IF NOT EXISTS source_session UUID;
ALTER TABLE project_memory ADD COLUMN IF NOT EXISTS verified BOOLEAN DEFAULT FALSE;
ALTER TABLE project_memory ADD COLUMN IF NOT EXISTS verified_by TEXT;
ALTER TABLE project_memory ADD COLUMN IF NOT EXISTS times_applied INT DEFAULT 0;
ALTER TABLE project_memory ADD COLUMN IF NOT EXISTS times_failed INT DEFAULT 0;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_patterns_needs_review ON learned_patterns(needs_review) WHERE needs_review = TRUE;
CREATE INDEX IF NOT EXISTS idx_patterns_verified ON learned_patterns(verified);
CREATE INDEX IF NOT EXISTS idx_patterns_source ON learned_patterns(source);
