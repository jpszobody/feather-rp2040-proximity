import time
import board
import busio
import displayio
import terminalio
from adafruit_display_text import label
import i2cdisplaybus
import adafruit_displayio_ssd1306
import adafruit_vl53l0x
from adafruit_ht16k33 import segments

# ==========================================
# ZONE THRESHOLDS (in mm)
# ==========================================
SAFE_ZONE = 500
CAUTION_ZONE = 300
OUT_OF_RANGE = 8190

# ==========================================
# PHASE 1: THE SETUP
# ==========================================

# 1. Reset any displays that might be stuck in memory
displayio.release_displays()

# 2. Open the I2C "Road" via the STEMMA QT port
i2c = busio.I2C(board.SCL, board.SDA)

# 3. Wake up the VL53L0X Sensor
sensor = adafruit_vl53l0x.VL53L0X(i2c)

# 4. Wake up the OLED Display
# 0x3C is the standard hardware address for these specific OLED screens
display_bus = i2cdisplaybus.I2CDisplayBus(i2c, device_address=0x3C)
display = adafruit_displayio_ssd1306.SSD1306(display_bus, width=128, height=32)

# 5. Create a "Canvas" and a "Text Box" for the screen
main_group = displayio.Group()
distance_label = label.Label(
    terminalio.FONT, 
    text="Waking up...", 
    color=0xFFFFFF, 
    x=10, 
    y=15
)
main_group.append(distance_label)
display.root_group = main_group  # Push our canvas to the physical screen

# 6. Wake up the 14-Segment LED Display
led_display = segments.Seg14x4(i2c)  # Default address 0x70
led_display.brightness = 0.5  # Start at medium brightness

time.sleep(1) # Brief pause so you can see the startup text

# ==========================================
# PHASE 2: THE LOOP
# ==========================================
print("Starting car proximity detector...")
print(f"SAFE: >{SAFE_ZONE}mm | CAUTION: {CAUTION_ZONE}-{SAFE_ZONE}mm | DANGER: <={CAUTION_ZONE}mm")

# Flash state for danger zone
flash_toggle = False

while True:
    try:
        # Read the distance from the sensor in millimeters
        dist_mm = sensor.range
        
        # If nothing in range, shut off both displays
        if dist_mm >= OUT_OF_RANGE:
            display.sleep = True
            led_display.fill(0)
            led_display.show()
            time.sleep(0.1)
            continue

        # Wake display if it was sleeping
        display.sleep = False

        # Determine zone
        if dist_mm <= CAUTION_ZONE:
            zone = "STOP!"
            # Flash OLED by toggling display inversion
            flash_toggle = not flash_toggle
            display.invert = flash_toggle
            led_display.brightness = 1.0 if flash_toggle else 0.3
        elif dist_mm <= SAFE_ZONE:
            zone = ">> CAUTION"
            display.invert = False
            led_display.brightness = 0.7
        else:
            zone = "SAFE"
            display.invert = False
            led_display.brightness = 0.5

        # LED: Always show distance
        dist_str = (str(dist_mm) + "    ")[:4]
        for i, char in enumerate(dist_str):
            led_display[i] = char if char != ' ' else ' '
        led_display.show()

        # OLED: Zone status
        distance_label.color = 0xFFFFFF
        distance_label.text = f"{zone} {dist_mm}mm"
        
        # Also print to the terminal
        print(f"[{zone:8}] Distance: {dist_mm}mm")
        
    except Exception as e:
        # If the sensor gets disconnected or glitches, don't crash the whole board
        led_display.fill(0)
        led_display[0] = 'E'
        led_display[1] = 'R'
        led_display[2] = 'R'
        led_display[3] = ' '
        led_display.show()
        distance_label.color = 0xFFFFFF
        distance_label.text = "Sensor Error!"
        display.invert = False
        print("Error:", e)

    # Wait 0.1 seconds before taking the next reading
    time.sleep(0.1)