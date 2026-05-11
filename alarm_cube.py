import asyncio
import os
import random
import lzstring
import json
from datetime import datetime
from bleak import BleakClient
from aiogram import Bot
from Crypto.Cipher import AES
from dotenv import load_dotenv

load_dotenv()

# Конфиг
TG_TOKEN = os.getenv("TG_TOKEN")
USER_ID  = int(os.getenv("USER_ID", 0))
ADDRESS  = os.getenv("CUBE_ADDRESS", "AB:12:34:5D:32:6D").upper()
NOTIFY_UUID = "28be4cb6-cd67-11e9-a32f-2a2ae2dbcce4"
TIMEOUT  = int(os.getenv("ANTISPAM_TIMEOUT", 20))

bot = Bot(token=TG_TOKEN)

# Магия ключей GAN
KEYS = [
    "NoRgnAHANATADDWJYwMxQOxiiEcfYgSK6Hpr4TYCs0IG1OEAbDszALpA",
    "NoNg7ANATFIQnARmogLBRUCs0oAYN8U5J45EQBmFADg0oJAOSlUQF0g",
    "NoRgNATGBs1gLABgQTjCeBWSUDsYBmKbCeMADjNnXxHIoIF0g",
    "NoRg7ANAzBCsAMEAsioxBEIAc0Cc0ATJkgSIYhXIjhMQGxgC6QA",
]

lz = lzstring.LZString()

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

class CubeGuard:
    def __init__(self):
        self.last_alert = 0
        self.key, self.iv = make_key_iv(ADDRESS)
        self.cube_colors = ["⬜", "🟨", "🟥", "🟧", "🟦", "🟩"]
        print(f"Ключи созданы для {ADDRESS}")

    async def notify_handler(self, sender, data):
        dec = decode_data(data, self.key, self.iv)
        bits = ''.join(bin(b + 256)[3:] for b in dec)
        mode = int(bits[0:4], 2)

        if mode == 2:  # Движение
            now_ts = asyncio.get_event_loop().time()
            now_str = datetime.now().strftime("%H:%M:%S")
            print(f"[{now_str}] ❗ Поворот зафиксирован!")

            if now_ts - self.last_alert > TIMEOUT:
                self.last_alert = now_ts
                c = random.sample(self.cube_colors, k=4)
                text = f"{c[0]}{c[1]} **CUBE MOVED!**\n{c[2]}{c[3]} **Alert!**"
                try:
                    await bot.send_message(chat_id=USER_ID, text=text, parse_mode="Markdown")
                except Exception as e:
                    print(f"Ошибка ТГ: {e}")

async def main():
    guard = CubeGuard()
    print(f"--- ОХРАНА ЗАПУЩЕНА (РЕЖИМ КЛИЕНТА) ---")
    
    while True:
        try:
            print(f"Попытка подключения к {ADDRESS}...")
            async with BleakClient(ADDRESS, timeout=15.0) as client:
                print("✅ Подключено! Жду движений...")
                await client.start_notify(NOTIFY_UUID, guard.notify_handler)
                
                # Держим соединение, пока клиент подключен
                while client.is_connected:
                    await asyncio.sleep(1)
                    
        except Exception as e:
            print(f"🔴 Ошибка/Отключение: {e}. Реконнект через 5 сек...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass