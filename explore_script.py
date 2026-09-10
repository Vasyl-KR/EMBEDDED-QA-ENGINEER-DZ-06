"""Part 1: port discovery and a raw, manual connection to the device.

No DeviceDriver here on purpose - this is the exploratory step before
wrapping the connection into a class.
"""

import serial
import serial.tools.list_ports

# 1. List all available COM ports
print("Available COM ports:")
ports = list(serial.tools.list_ports.comports())
if not ports:
    print("  (none found)")
for p in ports:
    print(f"  {p.device} - {p.description}")

if not ports:
    raise SystemExit("No COM port found - is the device connected?")

port_name = ports[0].device
print(f"\nUsing port: {port_name}")

# 2. Manual connection with the exact parameters the device expects
ser = serial.Serial(
    port=port_name,
    baudrate=115200,
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=2,
)

# 3. Send `help` and print the raw response as-is
ser.write(b"help\r\n")

print("\nRaw response:")
raw_bytes = ser.read(4096)  # grab whatever the device sent back within the timeout
print(repr(raw_bytes))

#print(raw_bytes.decode("utf-8", errors="replace"))

ser.close()
