import asyncio
import os
import random
from datetime import datetime
from bleak import BleakScanner
from aiogram import Bot
from dotenv import load_dotenv

# Подгружаем конфиг
load_dotenv()

TG_TOKEN = os.getenv("TG_TOKEN")
USER_ID  = int(os.getenv("USER_ID", 0))
ADDRESS  = os.getenv("CUBE_ADDRESS", "AB:12:34:5D:32:6D").upper()
TIMEOUT  = int(os.getenv("ANTISPAM_TIMEOUT", 20))

bot = Bot(token=TG_TOKEN)

import random  # Не забудь добавить этот импорт в самое начало файла!

class CubeWatch:
    def __init__(self):
        self.last_alert = 0
        self.loop = asyncio.get_running_loop()
        # Цвета кубика Рубика: белый, желтый, красный, оранжевый, синий, зеленый
        self.cube_colors = ["⬜", "🟨", "🟥", "🟧", "🟦", "🟩"]

    async def handle_detection(self, device, adv_data):
        if device.address.upper() == ADDRESS:
            current_time = self.loop.time()
            
            if current_time - self.last_alert > TIMEOUT:
                self.last_alert = current_time
                now = datetime.now().strftime("%H:%M:%S")
                rssi = adv_data.rssi
                
                # Генерируем 4 случайных эмодзи из списка
                c = random.sample(self.cube_colors, k=4)
                
                print(f"[{now}] 🚨 ТРЕВОГА! Сигнал: {rssi} dBm")
                
                try:
                    # Собираем сообщение с рандомными квадратиками
                    alert_text = (
                        f"{c[0]}{c[1]} **movement**\n"
                        f"{c[2]}{c[3]} **detected!**\n"
                        f" `{rssi} dBm` 📶 "
                    )
                    
                    await bot.send_message(
                        chat_id=USER_ID, 
                        text=alert_text, 
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"Ошибка TG: {e}")
                    
    def __init__(self):
        self.last_alert = 0
        self.loop = asyncio.get_running_loop()

    async def handle_detection(self, device, adv_data):
        # Фильтруем по адресу нашего куба
        if device.address.upper() == ADDRESS:
            current_time = self.loop.time()
            
            # Проверка антиспама
            if current_time - self.last_alert > TIMEOUT:
                self.last_alert = current_time
                now = datetime.now().strftime("%H:%M:%S")
                rssi = adv_data.rssi
                
                print(f"[{now}] 🚨 ТРЕВОГА! Сигнал: {rssi} dBm")
                
                try:
                    # Оформление по твоему шаблону
                    alert_text = (
                        "🟦🟧 **movement**\n"
                        "🟨🟩 **detected!**\n"
                        f" `{rssi} dBm` 📶 "
                    )
                    
                    await bot.send_message(
                        chat_id=USER_ID, 
                        text=alert_text, 
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"Ошибка TG: {e}")

async def main():
    if not TG_TOKEN or USER_ID == 0:
        print("❌ Ошибка: Проверь переменные в .env")
        return

    print(f"--- СИСТЕМА ОХРАНЫ ЗАПУЩЕНА ---")
    print(f"Цель: {ADDRESS} | Тайм-аут: {TIMEOUT}с")

    watcher = CubeWatch()
    
    # Слушаем эфир в активном режиме
    scanner = BleakScanner(
        detection_callback=watcher.handle_detection,
        scanning_mode="active"
    )

    try:
        await scanner.start()
        # Скрипт просто висит в памяти и ждет колбэков
        while True:
            await asyncio.sleep(1)
    finally:
        await scanner.stop()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nОхрана снята.")
