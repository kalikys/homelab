# Builder for the CV PDFs/TXT/DOCX, used by the autodeploy on LXC 104 (see ../autodeploy/).
FROM python:3.13-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends chromium fonts-inter fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir python-docx==1.2.0
ENV CHROME=/usr/bin/chromium
WORKDIR /cvgen
CMD ["python", "build_cv.py"]
