import asyncio
import os
import random
from datetime import datetime
from bleak import BleakScanner
from aiogram import Bot
from dotenv import load_dotenv

load_dotenv()

TG_TOKEN = os.getenv("TG_TOKEN")
USER_ID  = int(os.getenv("USER_ID", 0))
ADDRESS  = os.getenv("CUBE_ADDRESS", "AB:12:34:5D:32:6D").upper()
TIMEOUT  = int(os.getenv("ANTISPAM_TIMEOUT", 20))

bot = Bot(token=TG_TOKEN)

def decode_gan_adv(data, mac):
    """Декодирует рекламный пакет GAN куба"""
    # Ключ для XOR берется из MAC-адреса
    mac_bytes = bytes.fromhex(mac.replace(':', ''))
    key = mac_bytes[::-1]
    
    # XOR дешифровка
    decrypted = bytes(data[i] ^ key[i % len(key)] for i in range(len(data)))
    
    # Извлекаем данные (зависит от модели, но обычно так):
    # Байты 0-5: состояние граней (упрощенно)
    # Байт 12: счетчик ходов
    moves = decrypted[12] if len(decrypted) > 12 else 0
    return moves, decrypted.hex()

class CubeWatch:
    def __init__(self):
        self.last_alert = 0
        self.last_data = None
        self.loop = asyncio.get_running_loop()
        self.cube_colors = ["⬜", "🟨", "🟥", "🟧", "🟦", "🟩"]

async def handle_detection(self, device, adv_data):
        if device.address.upper() == ADDRESS:
            raw_data = adv_data.manufacturer_data.get(1)
            if not raw_data:
                return

            # Декодируем весь пакет
            _, decrypted_hex = decode_gan_adv(raw_data, ADDRESS)
            
            current_time = self.loop.time()
            now = datetime.now().strftime("%H:%M:%S")

            # Сравниваем ВЕСЬ дешифрованный пакет с предыдущим
            if decrypted_hex == self.last_data:
                return

            self.last_data = decrypted_hex
            rssi = adv_data.rssi
            
            # Попробуем вытащить ход из 12-го или 13-го байта для наглядности
            dec_bytes = bytes.fromhex(decrypted_hex)
            move_val = dec_bytes[12] if len(dec_bytes) > 12 else dec_bytes[-1]

            print(f"[{now}] ❗ Движение! MoveByte: {move_val} | Hex: {decrypted_hex[:30]}...")

            if current_time - self.last_alert > TIMEOUT:
                self.last_alert = current_time
                c = random.sample(self.cube_colors, k=4)
                
                try:
                    alert_text = (
                        f"{c[0]}{c[1]} **CUBE SENSORS CHANGED**\n"
                        f"{c[2]}{c[3]} **Data detected!**\n"
                        f" `{rssi} dBm` 📶 "
                    )
                    await bot.send_message(chat_id=USER_ID, text=alert_text, parse_mode="Markdown")
                except Exception as e:
                    print(f"Ошибка TG: {e}")

async def main():
    if not TG_TOKEN or USER_ID == 0:
        print("❌ Ошибка: Проверь .env")
        return

    print(f"--- ОХРАНА С ДЕКОДЕРОМ ЗАПУЩЕНА ---")
    print(f"Цель: {ADDRESS} | MAC-Key: {ADDRESS.replace(':', '')}")

    watcher = CubeWatch()
    scanner = BleakScanner(detection_callback=watcher.handle_detection, scanning_mode="active")

    try:
        await scanner.start()
        while True:
            await asyncio.sleep(1)
    finally:
        await scanner.stop()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())