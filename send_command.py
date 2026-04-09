import serial, time

def ubx(msg_cls, msg_id, payload: bytes):
    header = b'\xB5\x62' + bytes([msg_cls, msg_id]) + len(payload).to_bytes(2,'little')
    ck_a=ck_b=0
    for b in header[2:]+payload:
        ck_a = (ck_a + b) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return header + payload + bytes([ck_a, ck_b])

# ---- CFG-MSG (0x06 0x01), v1 (8-byte payload) ----
# payload = [msgClass, msgID, rateI2C, rateUART1, rateUART2, rateUSB, rateSPI, rateReserved]
def cfg_msg_allports(msgClass, msgID, rate=0):
    return ubx(0x06, 0x01, bytes([msgClass, msgID, rate, rate, rate, rate, rate, 0x00]))

# ---- CFG-PRT (0x06 0x00) per port ----
# inProtoMask/outProtoMask bits: UBX=0x01, NMEA=0x02, RTCM3=0x04
def cfg_prt(portID, baud=None, inMask=0x01, outMask=0x01):  # default keep UBX only
    if portID == 3:  # USB special (fixed layout)
        payload = bytes([3,0,0,0, 0,0,0,0, 0,0,0,0]) + inMask.to_bytes(2,'little') + outMask.to_bytes(2,'little') + b'\x00\x00'
        return ubx(0x06,0x00,payload)
    else:            # UART1=1, UART2=2
        mode   = 0x08D0  # 8N1
        baud   = 115200 if baud is None else baud
        flags  = 0
        payload = bytes([portID,0,0,0]) \
                + mode.to_bytes(4,'little') \
                + baud.to_bytes(4,'little') \
                + inMask.to_bytes(2,'little') \
                + outMask.to_bytes(2,'little') \
                + flags.to_bytes(2,'little')
        return ubx(0x06,0x00,payload)

# ===== SEND =====
ser = serial.Serial("/dev/ttyACM1", 115200, timeout=1)

# 1) Disable ALL NMEA sentences on ALL ports (F0 and F1 groups you showed)
nmea_f0 = [0x00,0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08,0x09,0x0A,0x0D,0x0F,0x10]  # common set (GGA..GST/ZDA/DTM/GRS/GNS/etc.)
nmea_f1 = [0x00,0x01,0x03,0x04,0x05,0x06]                                          # GNSS-specific set often present
for mid in nmea_f0:
    ser.write(cfg_msg_allports(0xF0, mid, 0x00)); ser.flush(); time.sleep(0.02)
for mid in nmea_f1:
    ser.write(cfg_msg_allports(0xF1, mid, 0x00)); ser.flush(); time.sleep(0.02)

# (Optional) Verify by asking for MON-VER or saving:
ser.write(ubx(0x0A, 0x04, b""))  # MON-VER poll

# 2) OPTIONAL: Disable UBX output on specific ports (leave only RTCM3 on UART1, for example)
#    USB: keep UBX only → outMask=0x01; to DISABLE UBX and keep nothing (or only RTCM3), set outMask accordingly.
#    Examples:
#    - USB keep UBX only:
ser.write(cfg_prt(portID=3, inMask=0x01, outMask=0x01))
#    - USB disable UBX too (no output): outMask=0x00
# ser.write(cfg_prt(portID=3, inMask=0x00, outMask=0x00))
#    - UART1 keep UBX+RTCM3 only, no NMEA:
# ser.write(cfg_prt(portID=1, baud=115200, inMask=0x01|0x04, outMask=0x01|0x04))

# 3) Persist to flash so it survives reboot
ser.write(ubx(0x06,0x09, b'\x00\x00\x00\x00\xFF\xFF\x00\x00\x00\x00'))  # CFG-CFG save current → BBR+Flash
ser.close()
 