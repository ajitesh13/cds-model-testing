FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DATA_DIR=/data PORT=8080
WORKDIR /app

COPY pyproject.toml ./
COPY thalamus ./thalamus
COPY app.py ./
COPY configs ./configs
COPY prompts ./prompts
COPY data/patient_2744.txt ./data/
# Editable install keeps configs/, prompts/ and data/ next to the package (the code resolves them relative to it).
RUN pip install -e . \
 && useradd --uid 10001 --create-home app \
 && mkdir -p /data && chown app /data
USER app
VOLUME /data
EXPOSE 8080

CMD streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true --browser.gatherUsageStats false
