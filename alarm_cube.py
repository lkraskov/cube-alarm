import asyncio
import os
import random
import json
import lzstring
from datetime import datetime
from bleak import BleakClient, BleakScanner
from aiogram import Bot
from Crypto.Cipher import AES
from dotenv import load_dotenv

load_dotenv()

TG_TOKEN = os.getenv("TG_TOKEN")
USER_ID  = int(os.getenv("USER_ID", 0))
# Accept both ADDRESS (used in .env) and legacy CUBE_ADDRESS.
ADDRESS  = os.getenv("ADDRESS", os.getenv("CUBE_ADDRESS", "AB:12:34:5D:32:6D")).upper()

NOTIFY_UUID = "28be4cb6-cd67-11e9-a32f-2a2ae2dbcce4"
WRITE_UUID  = "28be4a4a-cd67-11e9-a32f-2a2ae2dbcce4"

# Minimal interval between motion notifications (seconds).
MOTION_COOLDOWN = 600  # 10 minutes

# Canonical solved state. Verified against this cube on 2026-07-20 after its
# solved reference was reset in the GAN app (it then reports identity cp/ep).
SOLVED_REF = "UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB"

# Face index (U R F D L B) -> label. Standard scheme with white on top.
FACE_NAMES = {
    0: "⬜ White",
    1: "\U0001f7e5 Red",
    2: "\U0001f7e9 Green",
    3: "\U0001f7e8 Yellow",
    4: "\U0001f7e7 Orange",
    5: "\U0001f7e6 Blue",
}
WHITE_FACE = 0

bot = Bot(token=TG_TOKEN)
lz = lzstring.LZString()

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
        for i in range(16):
            ret[i + offset] = block[i] ^ iv[i]
    block = list(aes.decrypt(bytes(ret[:16])))
    for i in range(16):
        ret[i] = block[i] ^ iv[i]
    return ret


def encode_data(data, key, iv):
    aes = AES.new(key, AES.MODE_ECB)
    ret = list(data)
    for i in range(16):
        ret[i] ^= iv[i]
    ret[:16] = list(aes.encrypt(bytes(ret[:16])))
    if len(ret) > 16:
        offset = len(ret) - 16
        block = [ret[i + offset] ^ iv[i] for i in range(16)]
        ret[offset:] = list(aes.encrypt(bytes(block)))
    return ret


FACES = "URFDLB"  # face index 0..5, also the sticker letter for that face

# Standard Kociemba piece definitions. Corner i occupies CORNER_FACELETS[i] and
# carries the colours CORNER_COLORS[i], in matching order.
# Corners: URF UFL ULB UBR DFR DLF DBL DRB
CORNER_FACELETS = [[8, 9, 20], [6, 18, 38], [0, 36, 47], [2, 45, 11],
                   [29, 26, 15], [27, 44, 24], [33, 53, 42], [35, 17, 51]]
CORNER_COLORS = [[0, 1, 2], [0, 2, 4], [0, 4, 5], [0, 5, 1],
                 [3, 2, 1], [3, 4, 2], [3, 5, 4], [3, 1, 5]]
EDGE_FACELETS = [[5, 10], [7, 19], [3, 37], [1, 46], [32, 16], [28, 25],
                 [30, 43], [34, 52], [23, 12], [21, 41], [50, 39], [48, 14]]
EDGE_COLORS = [[0, 1], [0, 2], [0, 4], [0, 5], [3, 1], [3, 2],
               [3, 4], [3, 5], [2, 1], [2, 4], [5, 4], [5, 1]]


def render_facelets(cp, co, ep, eo):
    """Render permutation/orientation arrays into a 54-char URFDLB string."""
    facelet = ['?'] * 54
    for i, f in enumerate(FACES):
        facelet[i * 9 + 4] = f  # centers
    for i in range(8):
        p, o = cp[i], co[i]
        for j in range(3):
            facelet[CORNER_FACELETS[i][j]] = FACES[CORNER_COLORS[p][(j + o) % 3]]
    for i in range(12):
        p, o = ep[i], eo[i]
        for j in range(2):
            facelet[EDGE_FACELETS[i][j]] = FACES[EDGE_COLORS[p][(j + o) % 2]]
    return ''.join(facelet)


def parse_facelets(dec):
    """Decode a mode-4 (facelets) packet into a 54-char URFDLB string.

    Uses the canonical GAN Gen2 bit layout (afedotov/gan-web-bluetooth):
    corner perm @ bit 12 (7x3), corner ori @ bit 33 (7x2),
    edge perm @ bit 47 (11x4), edge ori @ bit 91 (11x1); the 8th corner
    and 12th edge are reconstructed from parity. Returns None if not mode 4.
    """
    bits = ''.join(bin(b + 256)[3:] for b in dec)
    if int(bits[0:4], 2) != 4:
        return None

    cp, co = [], []
    for i in range(7):
        cp.append(int(bits[12 + i * 3:15 + i * 3], 2))
        co.append(int(bits[33 + i * 2:35 + i * 2], 2))
    cp.append(28 - sum(cp))
    co.append((3 - sum(co) % 3) % 3)

    ep, eo = [], []
    for i in range(11):
        ep.append(int(bits[47 + i * 4:51 + i * 4], 2))
        eo.append(int(bits[91 + i:92 + i], 2))
    ep.append(66 - sum(ep))
    eo.append((2 - sum(eo) % 2) % 2)

    return render_facelets(cp, co, ep, eo)


def face_solved(facelets, face_index):
    """True if the given face matches the calibrated solved reference."""
    a = face_index * 9
    return facelets[a:a + 9] == SOLVED_REF[a:a + 9]


class HybridGuard:
    def __init__(self):
        self.last_motion_alert = 0
        self.scanner = None
        self.is_busy = False
        self.key, self.iv = make_key_iv(ADDRESS)
        self.colors = ["⬜", "\U0001f7e8", "\U0001f7e5", "\U0001f7e7", "\U0001f7e6", "\U0001f7e9"]
        # Faces already reported as solved, to avoid repeat notifications.
        self.notified_solved_faces = set()
        self.notified_full_solved = False

    async def read_facelets(self, client):
        """Subscribe, ask the cube for its state, return the facelet string (or None)."""
        result = {"facelets": None}

        def callback(sender, data):
            try:
                dec = decode_data(data, self.key, self.iv)
                s = parse_facelets(dec)
                if s is not None:
                    result["facelets"] = s
            except Exception as e:
                print(f"[{ts()}] callback error: {e}")

        await client.start_notify(NOTIFY_UUID, callback)
        # Actively request the facelets state (opcode 4). Without this the cube
        # only emits move packets and never sends its full state.
        req = [0] * 20
        req[0] = 4
        enc = bytes(encode_data(req, self.key, self.iv))
        for _ in range(4):
            try:
                await client.write_gatt_char(WRITE_UUID, enc, response=False)
            except Exception as e:
                print(f"[{ts()}] write error: {e}")
            await asyncio.sleep(1.0)
            if result["facelets"] is not None:
                break
        await client.stop_notify(NOTIFY_UUID)
        return result["facelets"]

    async def check_solve_state(self):
        """Pause scanning, connect and read the cube state.

        Returns the facelet string, or None if the state could not be read.
        """
        print(f"[{ts()}] Pausing scanner...")
        await self.scanner.stop()
        await asyncio.sleep(2.0)
        try:
            print(f"[{ts()}] Connecting...")
            async with BleakClient(ADDRESS, timeout=15.0) as client:
                print(f"[{ts()}] Connected. Reading state...")
                facelets = await self.read_facelets(client)
                if facelets is None:
                    print(f"[{ts()}] No state packet received.")
                else:
                    print(f"[{ts()}] Facelets: {facelets}")
                return facelets
        except Exception as e:
            print(f"[{ts()}] State check failed: {e}")
            return None
        finally:
            print(f"[{ts()}] Restarting scanner...")
            await self.scanner.start()

    async def report_solved(self, facelets):
        """Send notifications for newly solved faces / the whole cube."""
        if facelets == SOLVED_REF:
            if not self.notified_full_solved:
                self.notified_full_solved = True
                self.notified_solved_faces = set(range(6))
                await bot.send_message(USER_ID, "\U0001f389 **Cube solved!!**", parse_mode="Markdown")
                print(f"[{ts()}] Cube fully solved.")
            return

        self.notified_full_solved = False
        for idx, label in FACE_NAMES.items():
            if face_solved(facelets, idx):
                if idx not in self.notified_solved_faces:
                    self.notified_solved_faces.add(idx)
                    await bot.send_message(USER_ID, f"✅ **{label} face solved!**", parse_mode="Markdown")
                    print(f"[{ts()}] {label} face solved.")
            else:
                self.notified_solved_faces.discard(idx)

    async def detection_callback(self, device, adv_data):
        if device.address.upper() != ADDRESS:
            return
        now = asyncio.get_event_loop().time()
        if self.is_busy:
            return
        if now - self.last_motion_alert < MOTION_COOLDOWN:
            return
        self.is_busy = True
        self.last_motion_alert = now
        try:
            rssi = adv_data.rssi
            print(f"[{ts()}] ALERT!")
            # Read the state first so the alert can show white squares when the
            # white face is solved, instead of the usual random colours.
            facelets = await self.check_solve_state()
            white_ok = facelets is not None and face_solved(facelets, WHITE_FACE)
            c = ["⬜"] * 4 if white_ok else random.sample(self.colors, k=4)
            text = f"{c[0]}{c[1]} movement\n{c[2]}{c[3]} detected!\n `{rssi} dBm` \U0001f4f6"
            await bot.send_message(USER_ID, text, parse_mode="Markdown")
            if facelets is not None:
                await self.report_solved(facelets)
        except Exception as e:
            print(f"[{ts()}] Error: {e}")
        finally:
            self.is_busy = False


def ts():
    return datetime.now().strftime('%H:%M:%S')


async def main():
    guard = HybridGuard()
    print("--- GUARD v7 (Cooldown + Face Detection) ---")
    print(f"Target: {ADDRESS}")
    guard.scanner = BleakScanner(detection_callback=guard.detection_callback)
    await guard.scanner.start()
    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
