FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt requirements-cloud.txt ./
RUN pip install --no-cache-dir -r requirements-cloud.txt
COPY campuspulse ./campuspulse
COPY web/lms ./web/lms
RUN useradd --create-home appuser
USER appuser
EXPOSE 8080
CMD ["python", "-m", "campuspulse.lms_server", "--host", "0.0.0.0"]
