declare upper;

input leftBars = 2;
input rightBars = 2;
input toleranceBps = 0.0;

def pivotHigh = GetValue(
    high, rightBars, leftBars + rightBars
);
def pivotLow = GetValue(
    low, rightBars, leftBars + rightBars
);

def highMargin = pivotHigh * toleranceBps / 10000;
def lowMargin = pivotLow * toleranceBps / 10000;

def leftHighOK =
    fold a = 1 to leftBars + 1
    with ok1 = 1
    do ok1 and
       pivotHigh > GetValue(
           high, rightBars + a,
           leftBars + rightBars
       ) + highMargin;

def rightHighOK =
    fold b = 1 to rightBars + 1
    with ok2 = 1
    do ok2 and
       pivotHigh > GetValue(
           high, rightBars - b,
           leftBars + rightBars
       ) + highMargin;

def leftLowOK =
    fold c = 1 to leftBars + 1
    with ok3 = 1
    do ok3 and
       pivotLow < GetValue(
           low, rightBars + c,
           leftBars + rightBars
       ) - lowMargin;

def rightLowOK =
    fold d = 1 to rightBars + 1
    with ok4 = 1
    do ok4 and
       pivotLow < GetValue(
           low, rightBars - d,
           leftBars + rightBars
       ) - lowMargin;

def enoughHistory =
    BarNumber() > leftBars + rightBars;

plot ConfirmedHigh =
    if enoughHistory and leftHighOK and rightHighOK
    then pivotHigh
    else Double.NaN;

plot ConfirmedLow =
    if enoughHistory and leftLowOK and rightLowOK
    then pivotLow
    else Double.NaN;

ConfirmedHigh.SetPaintingStrategy(
    PaintingStrategy.POINTS
);
ConfirmedLow.SetPaintingStrategy(
    PaintingStrategy.POINTS
);

ConfirmedHigh.SetDefaultColor(Color.RED);
ConfirmedLow.SetDefaultColor(Color.GREEN);

ConfirmedHigh.SetLineWeight(3);
ConfirmedLow.SetLineWeight(3);

AddChartBubble(
    !IsNaN(ConfirmedHigh),
    ConfirmedHigh,
    "HIGH pivot " + GetYYYYMMDD()[rightBars]
    + " confirm " + GetYYYYMMDD(),
    Color.RED,
    yes
);

AddChartBubble(
    !IsNaN(ConfirmedLow),
    ConfirmedLow,
    "LOW pivot " + GetYYYYMMDD()[rightBars]
    + " confirm " + GetYYYYMMDD(),
    Color.GREEN,
    no
);
