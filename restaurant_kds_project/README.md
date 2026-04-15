# LISTO Restaurant Software

FastAPI webapp for a simple restaurant kitchen display system designed for two iPads:
- Station A
- Kitchen

## Features
- Dark theme, large-text senior-friendly dashboards
- Station A can create product orders
- Kitchen can receive Station A orders with sound + browser voice speech
- Kitchen can also create internal orders with sound-only alerts
- Admin can manage products and basic audio settings
- Admin can view order timing history and daily comparisons
- SQLite for local dev
- Railway-ready Procfile

## Routes
- `/station-a`
- `/kitchen`
- `/admin`
- `/admin/products`
- `/admin/audio`

## Local run
```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Notes
- This MVP stores audio files locally under `uploads/audio/`.
- In production you may want Postgres + persistent volume storage.
- Browser speech uses the Web Speech API in the client.
