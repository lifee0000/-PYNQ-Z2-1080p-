"""Frame geometry supported by the 1080p FPGA build; no image processing.

The V4 core accepts any even width up to MAX_WIDTH and height up to MAX_HEIGHT.
The Rice transport codec IPs accept only whole 64-pair groups per row, so the
compressed path is limited to the full-frame presets below. native/protocol.py
carries the same limits for the board service; a unit test keeps them equal.
"""
MAX_WIDTH, MAX_HEIGHT = 1920, 1080
# Processing resolutions offered by the application, largest first.
OUTPUT_PRESETS = ((1920, 1080), (1280, 720))
DEFAULT_OUTPUT = OUTPUT_PRESETS[0]


def valid(width, height):
    return (type(width) is int and type(height) is int and 4 <= width <= MAX_WIDTH
            and width % 2 == 0 and 3 <= height <= MAX_HEIGHT)


def require(width, height):
    if not valid(width, height):
        raise ValueError(f'even width 4..{MAX_WIDTH} and height 3..{MAX_HEIGHT} required')
    return width, height
