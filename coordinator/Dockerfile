FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY gentar/ gentar/
COPY scenarios/ /app/scenarios/
COPY tests/ tests/
# Unit tests gate the image build: any coordinator change busts the
# layer cache and reruns them, so every gate run (which builds this
# image) executes them without a workflow edit of its own. scenarios/
# must land BEFORE this layer: RealSuitesTest reads the real suite
# TOMLs (a scenario change re-runs the tests too — that is the point).
RUN python -m unittest discover -s tests

ENTRYPOINT ["python", "-m", "gentar"]
