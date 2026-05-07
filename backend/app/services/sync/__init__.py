# Sync control utilities — freeze/unfreeze incoming POS webhook processing
# without touching the upstream POS webhook registration. Necessary because
# Loyverse webhook DELETE→POST is unreliable ("already exists" cache).
# (POS webhook 처리 일시 차단 — Loyverse 측 등록은 그대로 보존)
