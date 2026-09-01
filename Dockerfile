FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY setup_db.py ./

ENV PYTHONPATH=/app

# Create startup script
RUN echo '#!/bin/bash\necho "Setting up database..."\npython setup_db.py\necho "Starting bot..."\nexec python -m src.bot' > start.sh && chmod +x start.sh

RUN useradd --create-home app && chown -R app:app /app
USER app

CMD ["./start.sh"]
