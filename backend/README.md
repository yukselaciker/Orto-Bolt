# SelcukBolt API

Bu backend, mevcut `core/bolton_logic.py` hesap motorunu bozmadan FastAPI ile web istemcilere acar.

## Gelistirme

```bash
python -m venv .venv-api
source .venv-api/bin/activate
pip install -r backend/requirements.txt -r requirements.txt
uvicorn backend.app.main:app --reload
```

## Uc Noktalar

- `GET /health`
- `GET /api/v1/metadata`
- `POST /api/v1/analysis/anterior`
- `POST /api/v1/analysis/overall`
- `POST /api/v1/analysis/combined`
- `POST /api/v1/mesh/info`
