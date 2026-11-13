import random, sys
LANG = {
 "en": dict(eyebrow="PYTHON SDK  ·  KYRGYZSTAN", tag1="Finik and FreedomPay payments,", tag2="signed and verified.",
            receipt="payment receipt", when="13.11.2026 19:44 · Bishkek", order="order", gateway="gateway", amount="amount",
            sum="1 500 KGS", checks=["signature", "paid to you", "amount", "live mode"], ok="OK", status="status",
            succeeded="SUCCEEDED", paid="PAID", paid_fs=48, verified="VERIFIED BY KGPAY"),
 "ru": dict(eyebrow="PYTHON SDK  ·  КЫРГЫЗСТАН", tag1="Платежи Finik и FreedomPay:", tag2="подписаны и проверены.",
            receipt="чек об оплате", when="13.11.2026 19:44 · Бишкек", order="заказ", gateway="шлюз", amount="сумма",
            sum="1 500 сом", checks=["подпись", "счёт ваш", "сумма", "не тест"], ok="ОК", status="статус",
            succeeded="ОПЛАЧЕН", paid="ОПЛАЧЕНО", paid_fs=29, verified="ПРОВЕРЕНО KGPAY"),
}
LG = sys.argv[1]
L = LANG[LG]
OUT = f"banner-{LG}.svg"
from svgtext import DISPLAY, LABEL, MONO, MONO_B, t, horn

W, H = 1280, 560
RED, DEEP, PAPER, INK, GOLD, MUTED = "#B5172F", "#A31329", "#FFFDF8", "#1B1B1F", "#F4B41A", "#6E6A66"
o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
     '<defs><clipPath id="r"><rect width="1280" height="560" rx="22"/></clipPath>',
     '<filter id="sh" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="14" stdDeviation="16" flood-color="#3a0610" flood-opacity=".45"/></filter></defs>',
     f'<g clip-path="url(#r)"><rect width="{W}" height="{H}" fill="{RED}"/>']
# shyrdak field of ram horns, mirrored row by row
for row in range(-1, 7):
    for col in range(-1, 14):
        x = col * 104 + (52 if row % 2 else 0)
        y = row * 96 + 40
        o.append(horn(x, y, 20, DEEP, 7, flip=bool(row % 2)))
o.append('</g>')

# left: wordmark
o.append(t(LABEL, L["eyebrow"], 76, 112, 30, GOLD, tracking=5))
o.append(t(DISPLAY, "kgpay", 64, 300, 214, PAPER, tracking=-4))
o.append(t(LABEL, L["tag1"], 78, 418, 40, PAPER, tracking=1))
o.append(t(LABEL, L["tag2"], 78, 462, 40, PAPER, tracking=1))
o.append(t(MONO_B, "$ pip install kgpay", 78, 516, 22, GOLD))

# right: the receipt
RX, RY, RW = 0, 0, 340
lines = []
LH, FS, PAD = 25, 15.5, 22
y = 52
def center(face, s, y, fs=FS, fill=INK, tr=0):
    lines.append(t(face, s, RW / 2, y, fs, fill, tracking=tr, anchor="middle"))
def row(l, r, y, bold=False, fill=INK):
    lines.append(t(MONO, l, PAD, y, FS, MUTED))
    lines.append(t(MONO_B if bold else MONO, r, RW - PAD, y, FS, fill, anchor="end"))
def dash(y):
    lines.append(f'<line x1="{PAD}" y1="{y}" x2="{RW-PAD}" y2="{y}" stroke="{INK}" stroke-width="1.5" stroke-dasharray="5 5" opacity=".55"/>')
center(MONO_B, "KGPAY", y, 20, tr=6); y += 24
center(MONO, L["receipt"], y, 13.5, MUTED); y += 20
center(MONO, L["when"], y, 13.5, MUTED); y += 20
dash(y); y += 30
row(L["order"], "order-1024", y); y += LH
row(L["gateway"], "Finik QR", y); y += LH
row(L["amount"], L["sum"], y, bold=True); y += 16
dash(y); y += 30
for label in L["checks"]:
    row(label, L["ok"], y, bold=True); y += LH
y -= 9
dash(y); y += 30
row(L["status"], L["succeeded"], y, bold=True); y += 22
# barcode
random.seed(7)
bx = PAD + 8
BAR_Y = y
while bx < RW * 0.5:
    w = random.choice([1.5, 1.5, 3, 4.5])
    lines.append(f'<rect x="{bx:.1f}" y="{y}" width="{w}" height="46" fill="{INK}"/>')
    bx += w + random.choice([2, 3, 4.5])
y += 72
lines.append(t(MONO_B, "Рахмат!", PAD + 8, y, 17, INK))
RH = y + 34

# zigzag paper
zz = 12
top = " ".join(f"L{x},{0 if (x // zz) % 2 else 7}" for x in range(0, RW + 1, zz))
bot = " ".join(f"L{x},{RH - (0 if (x // zz) % 2 else 7)}" for x in range(RW, -1, -zz))
paper = f'<path d="M0,7 {top} L{RW},{RH-7} {bot} Z" fill="{PAPER}"/>'

# stamp
stamp = (f'<g transform="translate({RW-88},{BAR_Y+24}) rotate(-10) scale(.82)" opacity=".88">'
         f'<rect x="-78" y="-42" width="156" height="84" rx="10" fill="none" stroke="{RED}" stroke-width="4"/>'
         f'<rect x="-70" y="-34" width="140" height="68" rx="6" fill="none" stroke="{RED}" stroke-width="1.5"/>'
         + t(LABEL, L["paid"], 0, 12, L["paid_fs"], RED, tracking=2, anchor="middle")
         + t(LABEL, L["verified"], 0, 27, 11, RED, tracking=1.5, anchor="middle") + '</g>')

cx, cy = 892, 30
o.append(f'<g transform="translate({cx},{cy}) rotate(3 {RW/2} {RH/2})" filter="url(#sh)">{paper}</g>')
o.append(f'<g transform="translate({cx},{cy}) rotate(3 {RW/2} {RH/2})">{"".join(lines)}{stamp}</g>')
o.append('</svg>')
open(OUT, "w").write("\n".join(o))
