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
    W, H = 1280, 500
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
         f'<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{line}"/></marker></defs>']

    def node(x, y, w, h, title, sub, dashed=False):
        dash = ' stroke-dasharray="8 7"' if dashed else ""
        o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{card}" stroke="{line}" stroke-width="2.5"{dash}/>')
        o.append(t(LABEL, title, x + w / 2, y + 56, 34, ink, tracking=2.5, anchor="middle"))
        if sub:
            o.append(t(MONO, sub, x + w / 2, y + 94, 18, muted, anchor="middle"))

    def arrow(x1, y1, x2, y2):
        o.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{line}" stroke-width="3" marker-end="url(#a)"/>')

    def badge(n, x, y):
        o.append(f'<circle cx="{x}" cy="{y}" r="16" fill="{red}" stroke="{card if theme == "light" else "#0d1117"}" stroke-width="4"/>')
        o.append(t(LABEL, str(n), x, y + 8.5, 24, chip_ink, anchor="middle"))

    def label(text, sub, x, y, anchor="middle"):
        o.append(t(MONO_B, text, x, y, 20, ink, anchor=anchor))
        if sub:
            o.append(t(MONO, sub, x, y + 26, 17, muted, anchor=anchor))

    node(20, 60, 220, 180, L["app"], None)
    o.append(f'<rect x="55" y="140" width="150" height="64" rx="32" fill="{red}"/>')
    o.append(t(DISPLAY, "kgpay", 130, 187, 48, chip_ink, anchor="middle"))
    node(470, 60, 300, 180, L["gw"], "Finik · FreedomPay")
    node(1010, 60, 250, 180, L["cust"], L["cust_sub"])
    node(470, 370, 300, 110, L["acc"], L["acc_sub"], dashed=True)

    arrow(240, 115, 467, 115); badge(1, 354, 115); label("create_payment()", None, 354, 92)
    arrow(470, 190, 243, 190); badge(3, 356, 190); label("parse_webhook()", L["verifies"], 356, 230)
    arrow(1010, 150, 773, 150); badge(2, 891, 150); label(L["pays"], None, 891, 124)
    arrow(620, 240, 620, 367); badge(4, 620, 300); label(L["settle"], L["never"], 650, 300, anchor="start")
    o.append("</svg>")
    return "\n".join(o)


for lg in ("en", "ru"):
    for th in ("light", "dark"):
        open(f"flow-{lg}-{th}.svg", "w").write(flow(th, lg))
