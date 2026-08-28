# Room-temperature model service — trains + serves predictions over MQTT.
# Runs off the Home Assistant host so training never touches HA resources.
# Uses the Debian-slim image (not Alpine) so scikit-learn/numpy install from
# prebuilt wheels — no C-extension compilation.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY model.py service.py ./

# Persist trained models across restarts by mounting a volume here.
VOLUME ["/models"]
ENV MODEL_DIR=/models

CMD ["python", "-u", "service.py"]
