import asyncio
import os
import random
import lzstring
import json
from datetime import datetime
from bleak import BleakClient, BleakScanner
from aiogram import Bot
from Crypto.Cipher import AES
from dotenv import load_dotenv

load_dotenv()

# Конфиг
TG_TOKEN = os.getenv("TG_TOKEN")
USER_ID  = int(os.getenv("USER_ID", 0))
ADDRESS  = os.getenv("CUBE_ADDRESS", "AB:12:34:5D:32:6D").upper()
NOTIFY_UUID = "28be4cb6-cd67-11e9-a32f-2a2ae2dbcce4"
TIMEOUT  = int(os.getenv("ANTISPAM_TIMEOUT", 15))

bot = Bot(token=TG_TOKEN)
lz = lzstring.LZString()

# Ключи GAN
KEYS = [
    "NoRgnAHANATADDWJYwMxQOxiiEcfYgSK6Hpr4TYCs0IG1OEAbDszALpA",
    "NoNg7ANATFIQnARmogLBRUCs0oAYN8U5J45EQBmFADg0oJAOSlUQF0g",
    "NoRgNATGBs1gLABgQTjCeBWSUDsYBmKbCeMADjNnXxHIoIF0g",
    "NoRg7ANAzBCsAMEAsioxBEIAc0Cc0ATJkgSIYhXIjhMQGxgC6QA",
]

def make_key_iv(mac_str):
    mac = [int(x, 16) for x in mac_str.split(':')]
    key = json.loads(lz.decompressFromEncodedURIComponent(KEYS[2]))
    iv  = json.loads(lz.decompressFromEncodedURIComponent(KEYS[3]))
    for i in range(6):
        key[i] = (key[i] + mac[5 - i]) % 255
        iv[i]  = (iv[i]  + mac[5 - i]) % 255
    return bytes(key), bytes(iv)

def decode_data(data, key, iv):
    aes = AES.new(key, AES.MODE_ECB)
    ret = list(data)
    if len(ret) > 16:
        offset = len(ret) - 16
        block = list(aes.decrypt(bytes(ret[offset:])))
        for i in range(16): ret[i + offset] = block[i] ^ iv[i]
    block = list(aes.decrypt(bytes(ret[:16])))
    for i in range(16): ret[i] = block[i] ^ iv[i]
    return ret

class HybridGuard:
    def __init__(self):
        self.last_alert = 0
        self.lock = asyncio.Lock()  # Блокировка для предотвращения InProgress
        self.key, self.iv = make_key_iv(ADDRESS)
        self.colors = ["⬜", "🟨", "🟥", "🟧", "🟦", "🟩"]

    async def check_solve_state(self):
        """Пытается подключиться и проверить состояние граней"""
        if self.lock.locked():
            return
            
        async with self.lock:
            # Даем адаптеру 1 секунду освободиться после сканирования
            await asyncio.sleep(1.5)
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Подключаюсь для анализа...")
            try:
                # Увеличиваем таймаут для надежности в Docker
                async with BleakClient(ADDRESS, timeout=15.0) as client:
                    def internal_callback(sender, data):
                        dec = decode_data(data, self.key, self.iv)
                        bits = ''.join(bin(b + 256)[3:] for b in dec)
                        if int(bits[0:4], 2) == 4:
                            facelets = [int(bits[16 + i*3 : 19 + i*3], 2) for i in range(54)]
                            # Проверяем, что куб полностью собран
                            if all(len(set(facelets[i*9 : (i+1)*9])) == 1 for i in range(6)):
                                asyncio.create_task(bot.send_message(USER_ID, "🎉 **Congrats, cube solved!!**", parse_mode="Markdown"))
                                print("🏆 Куб собран!")

                    await client.start_notify(NOTIFY_UUID, internal_callback)
                    await asyncio.sleep(4) # Ждем данные о состоянии
                    await client.stop_notify(NOTIFY_UUID)
            except Exception as e:
                # Ошибку InProgress теперь будем видеть реже, но если она есть - выводим красиво
                if "InProgress" in str(e):
                    print("⚠️ Адаптер все еще занят, пропускаю анализ...")
                else:
                    print(f"🔴 Ошибка анализа: {e}")

    async def detection_callback(self, device, adv_data):
        if device.address.upper() == ADDRESS:
            now = asyncio.get_event_loop().time()
            
            # Игнорируем пакеты, если мы уже в процессе атрисовки алерта или подключения
            if now - self.last_alert > TIMEOUT and not self.lock.locked():
                self.last_alert = now
                
                c = random.sample(self.colors, k=4)
                # Дизайн как на скрине
                text = (
                    f"{c[0]}{c[1]} movement\n"
                    f"{c[2]}{c[3]} detected!\n"
                    f" `{adv_data.rssi} dBm` 📶"
                )
                
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 ALERT!")
                asyncio.create_task(bot.send_message(USER_ID, text, parse_mode="Markdown"))
                
                # Запускаем анализ с задержкой
                asyncio.create_task(self.check_solve_state())

async def main():
    guard = HybridGuard()
    print(f"--- ГИБРИДНАЯ ОХРАНА ЗАПУЩЕНА (v2: No InProgress) ---")
    
    # Включаем сканер
    scanner = BleakScanner(detection_callback=guard.detection_callback)
    await scanner.start()
    
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await scanner.stop()

if __name__ == "__main__":
    asyncio.run(main())