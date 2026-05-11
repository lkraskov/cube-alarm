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
        self.last_move_count = -1
        self.loop = asyncio.get_running_loop()
        self.cube_colors = ["⬜", "🟨", "🟥", "🟧", "🟦", "🟩"]

    async def handle_detection(self, device, adv_data):
        if device.address.upper() == ADDRESS:
            # GAN кладет данные в manufacturer_data под ID 1
            raw_data = adv_data.manufacturer_data.get(1)
            if not raw_data:
                return

            # Декодируем!
            move_count, state_hex = decode_gan_adv(raw_data, ADDRESS)
            
            current_time = self.loop.time()
            now = datetime.now().strftime("%H:%M:%S")

            # Проверяем, изменился ли счетчик ходов
            if move_count == self.last_move_count:
                return

            self.last_move_count = move_count
            rssi = adv_data.rssi
            
            print(f"[{now}] 🎯 Ход №{move_count}! (Raw: {state_hex[:20]}...)")

            if current_time - self.last_alert > TIMEOUT:
                self.last_alert = current_time
                c = random.sample(self.cube_colors, k=4)
                
                try:
                    alert_text = (
                        f"{c[0]}{c[1]} **CUBE MOVED!**\n"
                        f"{c[2]}{c[3]} **Move count: {move_count}**\n"
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