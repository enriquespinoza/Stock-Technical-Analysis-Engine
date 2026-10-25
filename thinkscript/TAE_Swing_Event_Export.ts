
# TAE-TOS-001
# Confirmed Swing Event Export
# Fixed configuration: 2 left bars, 2 right bars, 0 bps
# Research-only simulated strategy

declare upper;

input exportHighs = no;

def enoughHistory = BarNumber() > 4;

def pivotHigh = high[2];
def pivotLow = low[2];

# Same strict 2/2 swing comparisons as Python
def highSignal =
    enoughHistory
    and pivotHigh > high[4]
    and pivotHigh > high[3]
    and pivotHigh > high[1]
    and pivotHigh > high;

def lowSignal =
    enoughHistory
    and pivotLow < low[4]
    and pivotLow < low[3]
    and pivotLow < low[1]
    and pivotLow < low;

# Export HIGH events in the first pass
AddOrder(
    OrderType.BUY_TO_OPEN,
    exportHighs and highSignal,
    open[-1],
    1,
    Color.RED,
    Color.RED,
    "TAE_EVT|HIGH|"
        + GetYYYYMMDD()[2]
        + "|" + GetYYYYMMDD()
        + "|" + pivotHigh
);

# Export LOW events in the second pass
AddOrder(
    OrderType.BUY_TO_OPEN,
    !exportHighs and lowSignal,
    open[-1],
    1,
    Color.GREEN,
    Color.GREEN,
    "TAE_EVT|LOW|"
        + GetYYYYMMDD()[2]
        + "|" + GetYYYYMMDD()
        + "|" + pivotLow
);

# Reset simulated position
AddOrder(
    OrderType.SELL_TO_CLOSE,
    yes,
    open[-1],
    1,
    Color.GRAY,
    Color.GRAY,
    "ExportExit"
);