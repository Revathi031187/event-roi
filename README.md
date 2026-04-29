# Event ROI Dashboard

AI-assisted **post-event ROI reporting**: plan analytics questions, run them against **Databricks Genie**, synthesize a structured **7-slide narrative** with **Gemini**, then export a branded **PowerPoint** deck.

---

## Features

- **Phase 1 — Plan:** Schema-aware prompts; Gemini proposes Genie natural-language questions.
- **Phase 2 — Query:** Parallel Genie execution against your Databricks SQL warehouse (or **demo mode** without credentials).
- **Phase 3 — Synthesize:** Gemini builds a fixed 7-slide executive report (summary, pipeline, funnel, audience, data quality, financial efficiency, risks/actions).
- **Outline editor** for bullets and insights before deck generation.
- **Full report** viewer (markdown), **slideshow preview** aligned with PPTX export rules, **PPTX download**, optional Google Slides import.
- **SQLite** persistence for report history and generated filenames.

---

## Architecture

| Layer | Stack |
|--------|--------|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS |
| Backend | FastAPI, Uvicorn, `google-genai`, Databricks SDK, python-pptx, SQLite |

The dev server proxies `/api` → `http://localhost:8000` (see `frontend/vite.config.ts`). In production, the API can serve the built SPA from `frontend/dist` when that folder exists.

---

## Prerequisites

- **Python** 3.11+ recommended  
- **Node.js** 18+ and npm  
- **Gemini API key** ([Google AI Studio](https://aistudio.google.com/))  
- **Databricks** workspace URL and PAT, plus a **Genie space ID**, unless you use **demo mode**

---

## Quick start (local development)

### 1. Backend

```bash
cd backend
python -m venv venv
```

**Windows:** `venv\Scripts\activate`  
**macOS/Linux:** `source venv/bin/activate`

```bash
copy .env.example .env   # Windows
# cp .env.example .env    # macOS/Linux — then edit .env
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Or run `backend/start.bat` on Windows (creates `venv`, installs deps, starts Uvicorn).

API base: **http://localhost:8000**  
Health: **GET** `/api/health`

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

App: **http://localhost:5173**

### 3. First run

1. Open the UI, enter an **event name** and optional context.  
2. Submit to run the three phases (plan → query → synthesize).  
3. Review the outline, then **Generate PowerPoint**.  
4. Download the `.pptx` from the completion screen.

---

## Environment variables

Create `backend/.env` (see `backend/.env.example`). Pydantic reads these (names are case-insensitive).

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Required for planning and synthesis (unless using demo-only flows that skip LLM — still recommended). |
| `GEMINI_PLAN_MODEL` | Optional. Default in code: `gemini-2.5-flash`. |
| `GEMINI_SYNTH_MODEL` | Optional. Default in code: `gemini-2.5-flash`. |
| `DATABRICKS_HOST` | Workspace URL, e.g. `https://xxx.cloud.databricks.com`. |
| `DATABRICKS_TOKEN` | Personal access token. |
| `GENIE_SPACE_ID` | Genie conversation space used for NL→SQL. |
| `DEMO_MODE` | Set `true` to use built-in sample data when Databricks is unavailable. |
| `CORS_ORIGINS` | JSON array of allowed origins, e.g. `["http://localhost:5173"]`. |

Never commit `.env` or secrets; they are listed in `.gitignore`.

---

## Production build (optional)

Build the frontend and run the API so it serves static files:

```bash
cd frontend && npm run build
cd ../backend && uvicorn main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** — FastAPI mounts `frontend/dist` when present.

---

## Project layout

```
ROI_Dashboard/
├── backend/
│   ├── main.py              # FastAPI app, CORS, static mount, download route
│   ├── config.py            # Settings from .env
│   ├── routers/generate.py  # Start job, SSE streams, PPT queue, reports CRUD
│   ├── services/            # Gemini, Genie, pipeline, PPTX, SQLite, outline parsing
│   ├── assets/              # e.g. Databricks logo for slides
│   └── requirements.txt
├── frontend/
│   ├── src/                 # React app (Dashboard, forms, outline editor, viewers)
│   ├── public/
│   └── package.json
├── README.md
└── .gitignore
```

---

## Repository

Source code: [github.com/jaison-samuel-d/event_roi](https://github.com/jaison-samuel-d/event_roi)

---

## License

Use and modify according to your organization’s policies. Add a `LICENSE` file if you want an explicit open-source terms.
