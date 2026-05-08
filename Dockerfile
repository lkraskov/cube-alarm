# Используем легкий образ Python
FROM python:3.11-slim

# Ставим зависимости для Bluetooth и компиляции расширений
RUN apt-get update && apt-get install -y \
    bluez \
    libbluetooth-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код и конфиг
COPY alarm_cube.py .


# Запускаем без буферизации логов, чтобы сразу видеть их в docker logs
CMD ["python", "-u", "alarm_cube.py"]
