# StudyLens AI

AI-powered exam readiness auditor. Upload your study material and course syllabus to receive a knowledge-gap analysis, readiness score, personalised revision plan, and an AI Study Tutor.

## Stack

- **Backend**: Python / Flask
- **AI**: Groq API (model: `openai/gpt-oss-120b`)
- **Auth**: JWT (PyJWT + flask-bcrypt)
- **DB (local)**: SQLite
- **DB (production)**: PostgreSQL via Neon (free tier)
- **Hosting**: Vercel (Hobby/free tier)
- **PDF extraction**: pdfplumber (embedded text), pytesseract/pdf2image (OCR fallback, not available on Vercel)

---

## Local Development

### 1. Clone and set up

```bash
git clone <your-repo-url>
cd studylens.ai
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in:
#   JWT_SECRET   -- generate with: python -c "import secrets; print(secrets.token_hex(32))"
#   GROQ_API_KEY -- from https://console.groq.com (free)
#   DATABASE_URL=studylens.db   (SQLite, local only)
#   UPLOAD_ROOT=uploads
#   FLASK_ENV=development
```

### 3. Run locally

```bash
python app.py
# Or with Flask CLI:
flask run
```

Open http://localhost:5000

### 4. Run tests

```bash
pytest -q
```

---

## Deploying to Vercel (Free/Hobby tier)

### Services required (all free tiers sufficient for demo use)

| Service | Purpose | Free tier |
|---|---|---|
| Vercel | Hosting Flask app | Yes (Hobby) |
| Neon | PostgreSQL database | Yes (0.5 GB storage) |
| Groq | AI inference | Yes (rate-limited) |

### Step 1: Push to GitHub

```bash
git add .
git commit -m "deploy: add Vercel configuration"
git push origin main
```

### Step 2: Create Neon database

1. Go to https://neon.tech and create a free account.
2. Create a new project (any region close to your Vercel region).
3. Copy the **Connection string** from the Neon dashboard. It looks like:
   ```
   postgresql://user:password@ep-xxx.us-east-1.aws.neon.tech/neondb?sslmode=require
   ```
4. Keep this for Step 4.

### Step 3: Import repository into Vercel

1. Go to https://vercel.com and create a free Hobby account.
2. Click **Add New Project** → **Import Git Repository**.
3. Select your StudyLens AI GitHub repository.
4. Vercel should auto-detect Python/Flask. Framework preset: **Other**.
5. Do NOT deploy yet — configure environment variables first.

### Step 4: Configure environment variables in Vercel

In the Vercel project → **Settings** → **Environment Variables**, add:

| Variable | Value |
|---|---|
| `GROQ_API_KEY` | Your Groq API key (from console.groq.com) |
| `JWT_SECRET` | Random 64-char hex (run `python -c "import secrets; print(secrets.token_hex(32))"`) |
| `DATABASE_URL` | Your Neon PostgreSQL connection string (from Step 2) |
| `UPLOAD_ROOT` | `/tmp/uploads` |
| `FLASK_ENV` | `production` |
| `GROQ_MODEL` | `openai/gpt-oss-120b` (optional, this is the default) |

### Step 5: Deploy

Click **Deploy** in the Vercel dashboard. The build will:
1. Install Python dependencies from `requirements.txt`.
2. Start the Flask app via `@vercel/python` pointing to `app.py`.

### Step 6: Initialise the database schema

After the first deploy, the database schema is created automatically when the first request hits the app (Flask calls `init_db()` in `create_app()`). You can verify by:
1. Registering an account on your deployed URL.
2. If registration succeeds, the schema is initialised.

Alternatively, run schema init manually using the Neon SQL editor:
- Go to Neon dashboard → SQL Editor → paste the `_SCHEMA_POSTGRES` from `db.py` and run it.

### Step 7: Test the deployment

1. **Register**: Create a new account at `https://your-app.vercel.app`
2. **Login**: Log in with the account
3. **Upload**: Upload a PDF study material + syllabus
4. **Analysis**: Verify readiness score, knowledge gaps, revision plan appear
5. **AI Tutor**: Open AI Study Tutor and ask a question
6. **Dashboard**: Check dashboard shows session history
7. **Sessions**: Verify history panel shows previous analyses

---

## Important limitations on Vercel free tier

| Limitation | Impact |
|---|---|
| **60-second function timeout** | The `/api/analyze` pipeline (PDF extraction + 2x Groq calls) can take up to 90 seconds locally. On Vercel free tier, requests timeout at 60 seconds. Large PDFs or slow Groq responses may fail. Mitigation: keep PDFs concise, Groq is fast (usually < 5s per call). |
| **No Tesseract/Poppler binaries** | OCR for scanned (image-only) PDFs is disabled on Vercel. PDFs with embedded text (the majority) work fine. The app gracefully handles this: `_OCR_AVAILABLE = False` at startup. |
| **Ephemeral `/tmp` storage** | Uploaded PDFs are saved to `/tmp/uploads` and deleted after the request completes. Files are not retrievable later — the extracted text is stored in the database instead. |
| **Cold starts** | Vercel serverless functions may have 1-3 second cold starts on first request. |

---

## Architecture on Vercel

```
Browser
  └── GET /            → Flask serves index.html + static files
  └── POST /auth/*     → Flask auth routes
  └── POST /api/analyze → Flask: validate PDF → extract text → Groq AI → store in Neon
  └── GET /api/sessions → Flask: query Neon PostgreSQL
  └── POST /api/*/tutor → Flask: load context from Neon → Groq AI → store response
```

All static files (`static/css/`, `static/js/`) are served through the Flask route via the single `app.py` handler.