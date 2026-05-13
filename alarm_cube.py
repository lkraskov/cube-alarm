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

TG_TOKEN = os.getenv("TG_TOKEN")
USER_ID  = int(os.getenv("USER_ID", 0))
ADDRESS  = os.getenv("CUBE_ADDRESS", "AB:12:34:5D:32:6D").upper()
NOTIFY_UUID = "28be4cb6-cd67-11e9-a32f-2a2ae2dbcce4"
TIMEOUT  = 15 

bot = Bot(token=TG_TOKEN)
lz = lzstring.LZString()

# Ключи
KEYS = ["NoRgnAHANATADDWJYwMxQOxiiEcfYgSK6Hpr4TYCs0IG1OEAbDszALpA", 
        "NoNg7ANATFIQnARmogLBRUCs0oAYN8U5J45EQBmFADg0oJAOSlUQF0g", 
        "NoRgNATGBs1gLABgQTjCeBWSUDsYBmKbCeMADjNnXxHIoIF0g", 
        "NoRg7ANAzBCsAMEAsioxBEIAc0Cc0ATJkgSIYhXIjhMQGxgC6QA"]

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
        self.scanner = None
        self.key, self.iv = make_key_iv(ADDRESS)
        self.colors = ["⬜", "🟨", "🟥", "🟧", "🟦", "🟩"]

    async def check_solve_state(self):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 Стопаю сканер для коннекта...")
        await self.scanner.stop()
        await asyncio.sleep(1.0) # Пауза на "остывание" адаптера

        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔗 Соединяюсь с {ADDRESS}...")
            async with BleakClient(ADDRESS, timeout=10.0) as client:
                print(f"✅ Коннект! Поиск сервисов...")
                
                def callback(sender, data):
                    dec = decode_data(data, self.key, self.iv)
                    bits = ''.join(bin(b + 256)[3:] for b in dec)
                    if int(bits[0:4], 2) == 4:
                        facelets = [int(bits[16 + i*3 : 19 + i*3], 2) for i in range(54)]
                        if all(len(set(facelets[i*9 : (i+1)*9])) == 1 for i in range(6)):
                            print("🏆 СОБРАН!")
                            asyncio.create_task(bot.send_message(USER_ID, "🎉 **Congrats, cube solved!!**"))

                await client.start_notify(NOTIFY_UUID, callback)
                await asyncio.sleep(3.0)
                await client.stop_notify(NOTIFY_UUID)
                print("🔌 Анализ завершен, отключаюсь.")
        except Exception as e:
            print(f"🔴 Ошибка анализа: {e}")
        finally:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ♻️ Возвращаю сканер в строй...")
            await self.scanner.start()

    async def detection_callback(self, device, adv_data):
        if device.address.upper() == ADDRESS:
            now = asyncio.get_event_loop().time()
            if now - self.last_alert > TIMEOUT:
                self.last_alert = now
                c = random.sample(self.colors, k=4)
                text = f"{c[0]}{c[1]} movement\n{c[2]}{c[3]} detected!\n `{adv_data.rssi} dBm` 📶"
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 ALERT!")
                asyncio.create_task(bot.send_message(USER_ID, text, parse_mode="Markdown"))
                asyncio.create_task(self.check_solve_state())

async def main():
    guard = HybridGuard()
    print(f"--- ГИБРИДНАЯ ОХРАНА v3 (Verbose Debug) ---")
    
    guard.scanner = BleakScanner(detection_callback=guard.detection_callback)
    await guard.scanner.start()
    
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await guard.scanner.stop()

if __name__ == "__main__":
    asyncio.run(main())