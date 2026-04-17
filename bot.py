import os
import telebot
import threading
import tempfile
from groq import Groq
from dotenv import load_dotenv
from flask import Flask

# Загрузка переменных
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not TELEGRAM_TOKEN or not GROQ_API_KEY:
    print("Ошибка: Токены не найдены!")
    exit()

bot = telebot.TeleBot(TELEGRAM_TOKEN)
groq_client = Groq(api_key=GROQ_API_KEY)

# --- ВЕБ-СЕРВЕР ДЛЯ UPTIMEROBOT ---
app = Flask(__name__)

@app.route('/')
def keep_alive():
    return "Бот работает и готов к приему сообщений!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
# ----------------------------------

SYSTEM_PROMPT = """
Ты — профессиональный редактор и личный помощник. Твоя задача — обрабатывать черновую расшифровку голосовых сообщений.
Правила обработки:
1. Очисти текст от слов-паразитов ("эээ", "ммм", "ну", "короче", "типа"), запинок и повторений.
2. Исправь все грамматические, пунктуационные и орфографические ошибки.
3. Обязательно разбивай текст на логические абзацы (если в нём несколько мыслей, этапов или шагов).
4. ОПРЕДЕЛЕНИЕ СТИЛЯ:
   - Если в тексте есть слова "для почты", "для email", "письмо", "руководителю" — сделай текст в строгом деловом стиле.
   - Если сказано "для чата", "в телеграм", "в битрикс" или стиль по смыслу неформальный — сделай текст свободным, приветливым и органично ДОБАВЬ несколько подходящих по смыслу эмодзи.
5. Выведи ТОЛЬКО готовый текст. Никаких вводных фраз вроде "Вот ваш текст".
"""

@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    msg = bot.reply_to(message, "⏳ Скачиваю аудио...")
    temp_dir = tempfile.gettempdir()
    file_name = os.path.join(temp_dir, f"voice_{message.message_id}.ogg")
    
    try:
        # Скачиваем файл
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        with open(file_name, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        bot.edit_message_text("🧠 Распознаю речь (Whisper Large)...", chat_id=message.chat.id, message_id=msg.message_id)
        
        # Распознавание через Groq API (Очень точное и не грузит сервер)
        with open(file_name, "rb") as audio_file:
            transcription = groq_client.audio.transcriptions.create(
                file=(file_name, audio_file.read()),
                model="whisper-large-v3",
                language="ru"
            )
        raw_text = transcription.text.strip()
        
        if not raw_text:
            bot.edit_message_text("❌ Не удалось распознать речь.", chat_id=message.chat.id, message_id=msg.message_id)
            return

        bot.edit_message_text("✨ Создаю красивый текст...", chat_id=message.chat.id, message_id=msg.message_id)
        
        # Обработка текста
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Исходный текст: {raw_text}"}
            ],
            temperature=0.3,
            max_tokens=2048
        )
        
        clean_text = response.choices[0].message.content.strip()
        
        # Отправка
        bot.reply_to(message, clean_text)
        bot.delete_message(chat_id=message.chat.id, message_id=msg.message_id)
        
    except Exception as e:
        bot.edit_message_text(f"Произошла ошибка: {e}", chat_id=message.chat.id, message_id=msg.message_id)
    
    finally:
        if os.path.exists(file_name):
            os.remove(file_name)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Отправь мне голосовое сообщение, а я превращу его в красивый, грамотный текст. 🎙️➡️📝")

if __name__ == "__main__":
    # Запускаем веб-сервер в отдельном потоке
    threading.Thread(target=run_web, daemon=True).start()
    print("Бот и веб-сервер запущены!")
    # Запускаем бота
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
