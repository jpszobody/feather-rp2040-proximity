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
STOP_ZONE = 100
OUT_OF_RANGE = 8190

# ==========================================
# PHASE 1: THE SETUP
# ==========================================

displayio.release_displays()

i2c = busio.I2C(board.SCL, board.SDA)
sensor = adafruit_vl53l0x.VL53L0X(i2c)

display_bus = i2cdisplaybus.I2CDisplayBus(i2c, device_address=0x3C)
display = adafruit_displayio_ssd1306.SSD1306(display_bus, width=128, height=32)

main_group = displayio.Group()

palette = displayio.Palette(2)
palette[0] = 0x000000
palette[1] = 0xFFFFFF

# Car silhouette (22w x 12h)
car_bm = displayio.Bitmap(22, 12, 2)
for x in range(5, 17):
    for y in range(0, 3):
        car_bm[x, y] = 1
for x in range(1, 21):
    for y in range(3, 8):
        car_bm[x, y] = 1
for x in range(1, 6):
    for y in range(8, 12):
        car_bm[x, y] = 1
for x in range(15, 21):
    for y in range(8, 12):
        car_bm[x, y] = 1

car_tg = displayio.TileGrid(car_bm, pixel_shader=palette, x=0, y=10)
main_group.append(car_tg)

# Scatter bitmap (90w x 28h), positioned at screen x=30, y=2
# Impact point in bitmap coords: x=89 (right edge), y=13 (middle)
# Pixels are sorted by distance from impact so they reveal outward
_scatter_raw = [
    # Very close (car body fragments)
    (89,10),(89,13),(89,16),(88,8),(88,11),(88,14),(88,18),(87,7),(87,12),
    (87,17),(87,21),(86,6),(86,10),(86,15),(86,20),(85,9),(85,14),(85,19),
    (84,5),(84,12),(84,17),(84,22),(83,8),(83,13),(83,18),(82,6),(82,11),
    (82,16),(82,21),(81,4),(81,10),(81,15),(81,20),(80,7),(80,12),(80,18),
    # Mid-range (stops at x=70 — half the previous spread)
    (78,5),(78,14),(78,22),(76,8),(76,17),(74,3),(74,12),(74,21),(72,6),
    (72,16),(70,9),(70,20),(70,24),
]

# Sort by distance from impact point (89, 13) — closest first
scatter_pixels = sorted(_scatter_raw, key=lambda p: (p[0]-89)**2 + (p[1]-13)**2)

scatter_bm = displayio.Bitmap(90, 28, 2)  # starts empty, filled during animation
scatter_tg = displayio.TileGrid(scatter_bm, pixel_shader=palette, x=30, y=2)
scatter_tg.hidden = True
main_group.append(scatter_tg)

# Stop wall
wall_bm = displayio.Bitmap(3, 32, 2)
for x in range(3):
    for y in range(32):
        wall_bm[x, y] = 1
wall_tg = displayio.TileGrid(wall_bm, pixel_shader=palette, x=124, y=0)
main_group.append(wall_tg)

# Distance label
dist_label = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=2, y=5)
main_group.append(dist_label)

display.root_group = main_group

# Car maps from x=0 (at SAFE_ZONE) to x=102 (at STOP_ZONE — touching wall)
CAR_MIN_X = 0
CAR_MAX_X = 102

# LED display
led_display = segments.Seg14x4(i2c)
led_display.brightness = 0.5

time.sleep(1)

# ==========================================
# PHASE 2: THE LOOP
# ==========================================
print("Starting car proximity detector...")

flash_toggle = False

CRASH_NONE    = 0
CRASH_SCATTER = 1
crash_state   = CRASH_NONE
scatter_frame = 0
PIXELS_PER_FRAME = 25  # pixels revealed per loop tick — ~0.25s for full spread

while True:
    try:
        dist_mm = sensor.range

        if dist_mm >= OUT_OF_RANGE:
            dist_label.text = ""
            car_tg.x = CAR_MIN_X
            car_tg.hidden = False
            scatter_tg.hidden = True
            scatter_bm.fill(0)
            crash_state = CRASH_NONE
            display.invert = False
            display.sleep = True
            led_display.fill(0)
            led_display.show()
            time.sleep(0.1)
            continue

        display.sleep = False
        dist_label.text = f"{dist_mm}mm"

        if dist_mm <= STOP_ZONE:
            # Start explosion immediately on first hit
            if crash_state == CRASH_NONE:
                crash_state = CRASH_SCATTER
                scatter_frame = 0
                scatter_bm.fill(0)
                car_tg.hidden = True
                scatter_tg.hidden = False

            # Reveal next wave of pixels outward from impact
            start = scatter_frame * PIXELS_PER_FRAME
            end = min(start + PIXELS_PER_FRAME, len(scatter_pixels))
            for i in range(start, end):
                x, y = scatter_pixels[i]
                scatter_bm[x, y] = 1
            if scatter_frame * PIXELS_PER_FRAME < len(scatter_pixels):
                scatter_frame += 1

            led_display[0] = 'S'
            led_display[1] = 'T'
            led_display[2] = 'O'
            led_display[3] = 'P'
            led_display.brightness = 1.0
            flash_toggle = not flash_toggle
            display.invert = flash_toggle

        else:
            if crash_state != CRASH_NONE:
                crash_state = CRASH_NONE
                scatter_bm.fill(0)
                car_tg.hidden = False
                scatter_tg.hidden = True
                display.invert = False

            clamped = max(STOP_ZONE, min(dist_mm, SAFE_ZONE))
            car_tg.x = int((1 - (clamped - STOP_ZONE) / (SAFE_ZONE - STOP_ZONE)) * CAR_MAX_X)
            led_display[0] = 'S'
            led_display[1] = 'L'
            led_display[2] = 'O'
            led_display[3] = 'W'
            led_display.brightness = 0.7

        led_display.show()
        print(f"Distance: {dist_mm}mm | {'STOP' if dist_mm <= STOP_ZONE else 'SLOW'}")

    except Exception as e:
        led_display.fill(0)
        led_display[0] = 'E'
        led_display[1] = 'R'
        led_display[2] = 'R'
        led_display[3] = ' '
        led_display.show()
        dist_label.text = "Err"
        car_tg.hidden = False
        scatter_tg.hidden = True
        scatter_bm.fill(0)
        crash_state = CRASH_NONE
        display.invert = False
        display.sleep = False
        print("Error:", e)

    time.sleep(0.1)
