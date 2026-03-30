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
SAFE_ZONE = 500   # Beyond this = out of useful range
STOP_ZONE = 100   # Within this = STOP
OUT_OF_RANGE = 8190  # Sensor sentinel value for "nothing detected"

# ==========================================
# PHASE 1: THE SETUP
# ==========================================

displayio.release_displays()

i2c = busio.I2C(board.SCL, board.SDA)
sensor = adafruit_vl53l0x.VL53L0X(i2c)

display_bus = i2cdisplaybus.I2CDisplayBus(i2c, device_address=0x3C)
display = adafruit_displayio_ssd1306.SSD1306(display_bus, width=128, height=32)

# --- Build the OLED display group ---
main_group = displayio.Group()

# Shared palette: index 0 = off, index 1 = on
palette = displayio.Palette(2)
palette[0] = 0x000000
palette[1] = 0xFFFFFF

# Car silhouette bitmap (22w x 12h), drawn as a side-profile
#
#      XXXXXXXXXX       <- cabin
#  XXXXXXXXXXXXXXXXXX   <- body
#  XXXXXXXXXXXXXXXXXX
#  XX              XX   <- wheel wells
#  XXXX          XXXX   <- wheels
#
car_bm = displayio.Bitmap(22, 12, 2)
for x in range(5, 17):       # cabin top
    for y in range(0, 3):
        car_bm[x, y] = 1
for x in range(1, 21):       # main body
    for y in range(3, 8):
        car_bm[x, y] = 1
for x in range(1, 6):        # left wheel
    for y in range(8, 12):
        car_bm[x, y] = 1
for x in range(15, 21):      # right wheel
    for y in range(8, 12):
        car_bm[x, y] = 1

car_tg = displayio.TileGrid(car_bm, pixel_shader=palette, x=0, y=10)
main_group.append(car_tg)

# Stop wall: vertical bar on the right edge
wall_bm = displayio.Bitmap(3, 32, 2)
for x in range(3):
    for y in range(32):
        wall_bm[x, y] = 1
wall_tg = displayio.TileGrid(wall_bm, pixel_shader=palette, x=124, y=0)
main_group.append(wall_tg)

# Distance label — top-left, above the car
dist_label = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=2, y=5)
main_group.append(dist_label)

# Crack overlay — hidden by default (palette[1] = black = invisible)
crack_palette = displayio.Palette(2)
crack_palette[0] = 0x000000
crack_palette[1] = 0x000000
crack_bm = displayio.Bitmap(128, 32, 2)

def draw_line(bm, x0, y0, x1, y1):
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        if 0 <= x0 < bm.width and 0 <= y0 < bm.height:
            bm[x0, y0] = 1
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy

# Cracks radiate from the impact point near the wall
ix, iy = 104, 15
draw_line(crack_bm, ix, iy, 68,  0)   # upper-left main crack
draw_line(crack_bm, ix, iy, 58, 31)   # lower-left main crack
draw_line(crack_bm, ix, iy, 42, 13)   # hard left crack
draw_line(crack_bm, ix, iy, 76,  0)   # upper crack
draw_line(crack_bm, ix, iy, 80, 31)   # lower crack
draw_line(crack_bm, 68,  0, 46,  0)   # branch along top
draw_line(crack_bm, 68,  0, 36, 11)   # branch down-left
draw_line(crack_bm, 58, 31, 34, 27)   # branch along bottom
draw_line(crack_bm, 42, 13, 16,  5)   # long branch upper
draw_line(crack_bm, 42, 13, 18, 22)   # long branch lower

crack_tg = displayio.TileGrid(crack_bm, pixel_shader=crack_palette, x=0, y=0)
main_group.append(crack_tg)  # on top of everything

display.root_group = main_group

# Car travel range: from x=0 (far) to x=100 (close to wall)
CAR_MIN_X = 0
CAR_MAX_X = 100  # wall is at x=124, car is 22px wide, leaves a 2px gap at closest

# LED display
led_display = segments.Seg14x4(i2c)
led_display.brightness = 0.5

time.sleep(1)

# ==========================================
# PHASE 2: THE LOOP
# ==========================================
print("Starting car proximity detector...")

flash_toggle = False

while True:
    try:
        dist_mm = sensor.range

        # Nothing in range — shut everything off and wait
        if dist_mm >= OUT_OF_RANGE:
            dist_label.text = ""
            car_tg.x = CAR_MIN_X
            crack_palette[1] = 0x000000
            display.invert = False
            display.sleep = True
            led_display.fill(0)
            led_display.show()
            time.sleep(0.1)
            continue

        display.sleep = False

        dist_label.text = f"{dist_mm}mm"

        if dist_mm <= STOP_ZONE:
            car_tg.x = CAR_MAX_X + 2       # jam car into the wall
            crack_palette[1] = 0xFFFFFF    # reveal crack overlay
            led_display.print("STOP")
            led_display.brightness = 1.0
            flash_toggle = not flash_toggle
            display.invert = flash_toggle
        else:
            clamped = max(0, min(dist_mm, SAFE_ZONE))
            car_tg.x = int((1 - clamped / SAFE_ZONE) * CAR_MAX_X)
            crack_palette[1] = 0x000000    # hide crack overlay
            led_display.print("SLOW")
            led_display.brightness = 0.7
            display.invert = False

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
        crack_palette[1] = 0x000000
        display.invert = False
        display.sleep = False
        print("Error:", e)

    time.sleep(0.1)
