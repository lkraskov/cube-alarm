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
# Минимальный интервал между уведомлениями о движении (секунды)
MOTION_COOLDOWN = 600  # 10 минут

bot = Bot(token=TG_TOKEN)
lz = lzstring.LZString()

KEYS = ["NoRgnAHANATADDWJYwMxQOxiiEcfYgSK6Hpr4TYCs0IG1OEAbDszALpA", 
        "NoNg7ANATFIQnARmogLBRUCs0oAYN8U5J45EQBmFADg0oJAOSlUQF0g", 
        "NoRgNATGBs1gLABgQTjCeBWSUDsYBmKbCeMADjNnXxHIoIF0g", 
        "NoRg7ANAzBCsAMEAsioxBEIAc0Cc0ATJkgSIYhXIjhMQGxgC6QA"]

# Цвета граней куба (индексы): 0=white, 1=yellow, 2=red, 3=orange, 4=blue, 5=green
FACE_NAMES = {0: "⬜ White", 1: "🟨 Yellow", 2: "🟥 Red", 3: "🟧 Orange", 4: "🟦 Blue", 5: "🟩 Green"}
EMOJI_COLORS = ["⬜", "🟨", "🟥", "🟧", "🟦", "🟩"]

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

def parse_facelets(dec):
    """Парсит декодированные данные и возвращает 54 цвета граней (6 граней по 9 стикеров)."""
    bits = ''.join(bin(b + 256)[3:] for b in dec)
    if int(bits[0:4], 2) != 4:
        return None
    # 54 стикера, каждый по 3 бита, начиная с 16-го бита
    return [int(bits[16 + i*3 : 19 + i*3], 2) for i in range(54)]

def check_face_solved(facelets, face_index):
    """Проверяет, собрана ли указанная грань (все 9 стикеров одного цвета)."""
    start = face_index * 9
    return len(set(facelets[start:start+9])) == 1

class HybridGuard:
    def __init__(self):
        self.last_motion_alert = 0
        self.scanner = None
        self.is_busy = False
        self.key, self.iv = make_key_iv(ADDRESS)
        self.colors = ["⬜", "🟨", "🟥", "🟧", "🟦", "🟩"]
        # Множество граней, о которых уже уведомили как о собранных
        self.notified_solved_faces = set()

    async def check_solve_state(self):
        self.is_busy = True
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 Пауза сканера...")
        await self.scanner.stop()
        await asyncio.sleep(2.0) 

        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔗 Коннект...")
            async with BleakClient(ADDRESS, timeout=12.0) as client:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Подключился! Подписываюсь на нотификации...")
                
                notify_events = []

                def callback(sender, data):
                    try:
                        ts = datetime.now().strftime('%H:%M:%S')
                        print(f"[{ts}] 📦 RAW data ({len(data)} байт): {data.hex()}")
                        
                        dec = decode_data(data, self.key, self.iv)
                        print(f"[{ts}] 🔓 DEC data ({len(dec)} байт): {bytes(dec).hex()}")
                        
                        bits = ''.join(bin(b + 256)[3:] for b in dec)
                        packet_type = int(bits[0:4], 2)
                        print(f"[{ts}] 📊 Первые 32 бита: {bits[:32]}, тип пакета: {packet_type}")
                        
                        facelets = parse_facelets(dec)
                        if facelets is None:
                            print(f"[{ts}] ⏭ Не state-пакет (тип {packet_type}), пропускаю")
                            return

                        print(f"[{ts}] 🎯 State-пакет! 54 стикера: {facelets}")
                        notify_events.append(facelets)
                        
                        # Проверка каждой грани на собранность
                        for face_idx in range(6):
                            colors_in_face = facelets[face_idx*9 : (face_idx+1)*9]
                            unique_colors = set(colors_in_face)
                            center_color = colors_in_face[4]
                            print(f"[{ts}]   Грань {face_idx} ({FACE_NAMES[face_idx]}): "
                                  f"центр={EMOJI_COLORS[center_color]}, "
                                  f"цвета={colors_in_face}, "
                                  f"уникальных={len(unique_colors)}")
                            
                            if len(unique_colors) == 1 and face_idx not in self.notified_solved_faces:
                                color_name = FACE_NAMES[face_idx]
                                self.notified_solved_faces.add(face_idx)
                                msg = f"✅ **{color_name} face solved!**"
                                print(f"[{ts}] ✅ {msg}")
                                asyncio.create_task(bot.send_message(USER_ID, msg))

                        # Проверка полной сборки куба
                        if all(len(set(facelets[i*9 : (i+1)*9])) == 1 for i in range(6)):
                            print(f"[{ts}] 🎉 Куб полностью собран!")
                            asyncio.create_task(bot.send_message(USER_ID, "🎉 **Congrats, cube solved!!**"))
                    except Exception as e:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔴 Ошибка в callback: {e}")

                await client.start_notify(NOTIFY_UUID, callback)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 👂 Слушаю нотификации 4 секунды...")
                await asyncio.sleep(4.0)
                await client.stop_notify(NOTIFY_UUID)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 Нотификации остановлены. "
                      f"Получено {len(notify_events)} state-пакетов")
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔴 Мимо: {e}")
        finally:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ♻️ Рестарт сканера...")
            await self.scanner.start()
            self.is_busy = False

    async def detection_callback(self, device, adv_data):
        if device.address.upper() != ADDRESS:
            return

        now = asyncio.get_event_loop().time()

        # Anti-flood: не обрабатываем, если уже заняты проверкой
        if self.is_busy:
            return

        # Anti-flood: проверяем кулдаун движения
        if now - self.last_motion_alert < MOTION_COOLDOWN:
            return

        # Блокируем повторный вход (атомарная проверка + установка)
        self.is_busy = True
        self.last_motion_alert = now

        try:
            c = random.sample(self.colors, k=4)
            text = f"{c[0]}{c[1]} movement\n{c[2]}{c[3]} detected!\n `{adv_data.rssi} dBm` 📶"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 ALERT!")
            await bot.send_message(USER_ID, text, parse_mode="Markdown")
            
            # После движения проверяем состояние куба
            await self.check_solve_state()
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔴 Ошибка: {e}")
            self.is_busy = False

async def main():
    guard = HybridGuard()
    print(f"--- ОХРАНА v5 (Cooldown + Face Detection) ---")
    guard.scanner = BleakScanner(detection_callback=guard.detection_callback)
    await guard.scanner.start()
    while True: await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
