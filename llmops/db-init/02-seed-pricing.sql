-- Lokalne modele Ollama sa darmowe, ale 'model_pricing' laczy sie po
-- dokladnej nazwie modelu (mp.model = c.model) -- 'ANY' nie jest wildcardem i
-- nie dopasuje sie do zadnego wywolania. Kazdy uzywany model Ollama trzeba
-- dopisac osobnym wierszem, po nazwie, np.:
-- INSERT INTO model_pricing (provider, model, usd_per_mtok_in, usd_per_mtok_out)
-- VALUES ('ollama', 'qwen3:4b', 0.00, 0.00);
INSERT INTO model_pricing (provider, model, usd_per_mtok_in, usd_per_mtok_out) VALUES
    ('groq',       'llama-3.3-70b-versatile',                    0.00,  0.00),
    ('gemini',     'gemini-flash-latest',                        0.00,  0.00),
    ('gemini',     'gemini-2.0-flash',                           0.00,  0.00),
    ('openrouter', 'meta-llama/llama-3.3-70b-instruct:free',     0.00,  0.00),
    ('openrouter', 'meta-llama/llama-4-maverick:free',           0.00,  0.00),
    ('openrouter', 'qwen/qwen3-235b-a22b:free',                  0.00,  0.00),
    ('openrouter', 'google/gemma-3-27b-it:free',                 0.00,  0.00),
    ('openrouter', 'openai/gpt-4o-mini',                         0.15,  0.60)
ON CONFLICT (provider, model, valid_from) DO NOTHING;
