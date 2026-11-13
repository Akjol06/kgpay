from svgtext import DISPLAY, LABEL, MONO, MONO_B, t

T = {
 "en": dict(app="YOUR APP", gw="PAYMENT GATEWAY", cust="CUSTOMER", cust_sub="QR · card · wallet", acc="YOUR ACCOUNT",
            acc_sub="money lands here", pays="pays", verifies="verifies everything", settle="settlement", never="never through kgpay", fs=30),
 "ru": dict(app="ВАШ СЕРВИС", gw="ПЛАТЁЖНЫЙ ШЛЮЗ", cust="ПОКУПАТЕЛЬ", cust_sub="QR · карта · кошелёк", acc="ВАШ СЧЁТ",
            acc_sub="деньги приходят сюда", pays="платит", verifies="проверяет всё", settle="зачисление", never="минуя kgpay", fs=30),
}

def flow(theme, lg):
    L = T[lg]
    if theme == "light":
        card, line, ink, muted, red, chip_ink = "#FFFDF8", "#1B1B1F", "#1B1B1F", "#6E6A66", "#B5172F", "#FFFDF8"
    else:
        card, line, ink, muted, red, chip_ink = "#161B22", "#C9D1D9", "#E6EDF3", "#8B949E", "#E0364E", "#FFFDF8"
    W, H = 1280, 470
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
         f'<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{line}"/></marker></defs>']
    def node(x, y, w, h, title, sub, dashed=False):
        dash = ' stroke-dasharray="7 6"' if dashed else ""
        o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{card}" stroke="{line}" stroke-width="2"{dash}/>')
        o.append(t(LABEL, title, x + w / 2, y + 52, 30, ink, tracking=3, anchor="middle"))
        if sub:
            o.append(t(MONO, sub, x + w / 2, y + 84, 15.5, muted, anchor="middle"))
    def arrow(x1, y1, x2, y2):
        o.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{line}" stroke-width="2.5" marker-end="url(#a)"/>')
    def step(n, x, y, text, sub=None, anchor="middle"):
        tw = MONO_B.width(text, 16)
        if anchor == "middle":
            cx0 = x - (tw + 34) / 2
        else:
            cx0 = x
        o.append(f'<circle cx="{cx0 + 13}" cy="{y - 6}" r="13" fill="{red}"/>')
        o.append(t(LABEL, str(n), cx0 + 13, y + 2, 21, chip_ink, anchor="middle"))
        o.append(t(MONO_B, text, cx0 + 34, y, 16, ink))
        if sub:
            o.append(t(MONO, sub, cx0 + 34, y + 22, 14.5, muted))

    # nodes
    node(30, 50, 250, 170, L["app"], None)
    o.append(f'<rect x="85" y="128" width="140" height="58" rx="29" fill="{red}"/>')
    o.append(t(DISPLAY, "kgpay", 155, 170, 44, chip_ink, anchor="middle"))
    node(560, 50, 300, 170, L["gw"], "Finik · FreedomPay")
    node(1020, 50, 230, 170, L["cust"], L["cust_sub"])
    node(560, 330, 300, 110, L["acc"], L["acc_sub"], dashed=True)

    # 1: create payment
    arrow(280, 105, 558, 105)
    step(1, 419, 80, "create_payment()", None)
    # 3: webhook back
    arrow(560, 170, 282, 170)
    step(3, 296, 208, "parse_webhook()", L["verifies"], anchor="start")
    # 2: customer pays
    arrow(1020, 135, 862, 135)
    step(2, 941, 110, L["pays"], None)
    # 4: money
    arrow(710, 220, 710, 328)
    step(4, 730, 270, L["settle"], L["never"], anchor="start")
    o.append("</svg>")
    return "\n".join(o)

for lg in ("en", "ru"):
    for th in ("light", "dark"):
        open(f"flow-{lg}-{th}.svg", "w").write(flow(th, lg))
