# StudyLens AI — Production Dockerfile
# Deploys on Render (free tier) as a single-worker gunicorn service.

FROM python:3.11-slim

# Install system dependencies for PDF text extraction and OCR.
# tesseract-ocr: OCR engine used by pytesseract.
# poppler-utils: provides pdfinfo/pdftoppm used by pdf2image.
# Clean apt cache in the same layer to minimise image size.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tesseract-ocr \
      poppler-utils \
 && rm -rf /var/lib/apt/lists/*

# Copy project source into the image.
COPY . /app

WORKDIR /app

# Install Python dependencies without caching downloaded packages.
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port Render (or any host) injects via $PORT.
# The CMD below uses $PORT at runtime; EXPOSE here is documentation only.
EXPOSE 10000

# Run Flask through Gunicorn.
# --timeout 120  matches the 120-second AI analysis pipeline SLA.
# --workers 1    appropriate for a SQLite-backed single-instance deployment.
# --bind         listens on the port Render provides via $PORT.
CMD ["sh", "-c", "gunicorn app:app --timeout 120 --workers 1 --bind 0.0.0.0:${PORT:-10000}"]
