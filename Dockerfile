FROM python:3.9-slim

# Установка системных зависимостей включая ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    wget \
    curl \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Создание рабочей директории
WORKDIR /app

# Копирование requirements.txt и установка Python зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода приложения
COPY . .

# Создание директорий для логов и базы данных
RUN mkdir -p /app/logs /app/data

# Установка прав доступа
RUN chmod +x /app

# Экспорт порта (если нужен для webhook)
EXPOSE 8080

# Запуск бота
CMD ["python", "bot.py"bot