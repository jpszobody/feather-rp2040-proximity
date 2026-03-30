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

# Debris overlay — scattered pixels overlaid on top of car when crashing
# palette[0] is transparent so the car shows through underneath
debris_palette = displayio.Palette(2)
debris_palette[0] = 0x000000
debris_palette.make_transparent(0)
debris_palette[1] = 0x000000  # hidden until crash
debris_bm = displayio.Bitmap(128, 32, 2)

# Helper to draw a short line segment into the bitmap
def draw_seg(x0, y0, x1, y1):
    dx=abs(x1-x0); dy=abs(y1-y0)
    sx=1 if x0<x1 else -1; sy=1 if y0<y1 else -1; err=dx-dy
    while True:
        if 0<=x0<128 and 0<=y0<32: debris_bm[x0,y0]=1
        if x0==x1 and y0==y1: break
        e2=2*err
        if e2>-dy: err-=dy; x0+=sx
        if e2<dx:  err+=dx; y0+=sy

# Short chunks flying left from the car (right side of screen)
for seg in [(98,7,93,3),(96,24,90,28),(100,14,95,17),
            (86,3,82,1),(83,27,78,30),(79,10,74,7),(81,21,75,25),
            (71,5,67,2),(69,26,64,29),(60,8,55,5),(61,22,56,25)]:
    draw_seg(*seg)

# Individual scattered pixel pairs at medium/long range
for (x,y) in [(72,13),(73,14),(66,16),(65,17),(58,8),(59,8),
              (55,20),(56,20),(48,5),(49,5),(45,25),(46,25),
              (62,2),(38,11),(39,11),(35,18),(40,28),(42,29),
              (30,7),(28,22),(20,14),(22,15),(15,9),(18,24)]:
    debris_bm[x,y]=1

debris_tg = displayio.TileGrid(debris_bm, pixel_shader=debris_palette, x=-128, y=0)
main_group.append(debris_tg)  # on top of everything

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
            debris_tg.x = -128
            display.invert = False
            display.sleep = True
            led_display.fill(0)
            led_display.show()
            time.sleep(0.1)
            continue

        display.sleep = False

        dist_label.text = f"{dist_mm}mm"

        clamped = max(0, min(dist_mm, SAFE_ZONE))
        car_tg.x = int((1 - clamped / SAFE_ZONE) * CAR_MAX_X)

        if dist_mm <= STOP_ZONE:
            debris_tg.x = 0               # reveal debris
            led_display[0] = 'S'
            led_display[1] = 'T'
            led_display[2] = 'O'
            led_display[3] = 'P'
            led_display.brightness = 1.0
            flash_toggle = not flash_toggle
            display.invert = flash_toggle
        else:
            debris_tg.x = -128            # hide debris off-screen
            led_display[0] = 'S'
            led_display[1] = 'L'
            led_display[2] = 'O'
            led_display[3] = 'W'
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
        debris_tg.x = -128
        display.invert = False
        display.sleep = False
        print("Error:", e)

    time.sleep(0.1)
