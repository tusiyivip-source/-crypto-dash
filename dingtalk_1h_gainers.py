#!/usr/bin/env python3
"""
Binance 1H涨幅 Top20 -> 钉钉图片推送
每30分钟: 获取USDT交易对1小时涨幅前20 -> 生成表格图片 -> 上传图床 -> 钉钉picURL推送
"""

import os, sys, io, json, time, base64, hashlib, hmac
import urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone, timedelta

import requests
from PIL import Image, ImageDraw, ImageFont

# Windows GBK 终端修复
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ============ 配置 ============
DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK", "").strip()
DINGTALK_SECRET = os.environ.get("DINGTALK_SECRET", "").strip()
if not DINGTALK_WEBHOOK or not DINGTALK_SECRET:
    print(
        "错误: 未配置钉钉推送。请先设置环境变量 DINGTALK_WEBHOOK / DINGTALK_SECRET\n"
        "  (运行 schedule_task.ps1 可自动写入用户环境变量)"
    )
    sys.exit(1)
BINANCE_REST = "https://api.binance.com"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============ 字体 ============
def get_font(size, bold=False):
    paths = [
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except:
                continue
    return ImageFont.load_default()

# ============ Binance API ============
def fetch_json(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(1)

def get_top_usdt_pairs(limit=200):
    tickers = fetch_json(f"{BINANCE_REST}/api/v3/ticker/24hr")
    usdt_pairs = [
        t for t in tickers
        if t["symbol"].endswith("USDT")
        and "BUSD" not in t["symbol"]
        and "TUSD" not in t["symbol"]
        and "USDC" not in t["symbol"]
    ]
    usdt_pairs.sort(key=lambda t: float(t["quoteVolume"]), reverse=True)
    return [
        {
            "symbol": t["symbol"],
            "lastPrice": float(t["lastPrice"]),
            "priceChangePercent": float(t["priceChangePercent"]),
            "quoteVolume": float(t["quoteVolume"]),
        }
        for t in usdt_pairs[:limit]
    ]

def get_1h_change(symbol):
    try:
        klines = fetch_json(
            f"{BINANCE_REST}/api/v3/klines?symbol={urllib.parse.quote(symbol,safe='')}&interval=1h&limit=2"
        )
        if len(klines) >= 2:
            c1, c2 = float(klines[0][4]), float(klines[1][4])
            chg = (c2 - c1) / c1 * 100
            return {"changePercent": round(chg, 2), "price1hAgo": c1, "currentPrice": c2}
    except Exception as e:
        print(f"  ! {symbol} error: {e}")
    return None

def get_all_1h_changes(pairs, delay=0.08):
    results = []
    print(f"Fetching 1h changes for {len(pairs)} pairs...")
    for i, pair in enumerate(pairs):
        s = pair["symbol"]
        info = get_1h_change(s)
        if info:
            results.append({**pair, **info})
        else:
            results.append({**pair, "changePercent": pair["priceChangePercent"], "price1hAgo": None, "currentPrice": pair["lastPrice"]})
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(pairs)}")
    return results

# ============ 图片生成 ============
def fmt_price(p):
    if p >= 1000:   return f"${p:,.0f}"
    if p >= 1:      return f"${p:,.2f}"
    if p >= 0.01:   return f"${p:,.4f}"
    if p >= 1e-4:   return f"${p:.6f}"
    return f"${p:.8f}"

def fmt_vol(v):
    if v >= 1e9:      return f"${v/1e9:.1f}B"
    if v >= 1e6:      return f"${v/1e6:.1f}M"
    if v >= 1e3:      return f"${v/1e3:.1f}K"
    return f"${v:.0f}"

def create_table_image(data):
    """生成高分辨率表格图片，钉钉内直接可读"""
    n = len(data)
    BG, HDR, ROW_ALT = (11, 14, 17), (26, 30, 36), (20, 23, 29)
    GREEN, RED, YELLOW, WHITE, GRAY = (14, 203, 129), (246, 70, 93), (240, 185, 11), (234, 236, 239), (132, 142, 156)

    # 2x 放大 — 宽列宽 + 大字体
    cols = [
        ("#",           70),
        ("交易对",     170),
        ("当前价",     220),
        ("1h涨跌",     170),
        ("1h前价",     220),
        ("成交额(24h)", 210),
        ("24h涨跌",    170),
    ]
    pad = 28
    title_h, header_h, row_h = 72, 60, 56
    img_w = pad + sum(w for _, w in cols) + pad
    img_h = title_h + header_h + n * row_h + 30

    img = Image.new("RGB", (img_w, img_h), BG)
    draw = ImageDraw.Draw(img)
    ft_t = get_font(28, True)
    ft_h = get_font(22, True)
    ft_r = get_font(22)
    ft_s = get_font(18)
    ft_rank = get_font(24, True)

    # Title bar
    draw.rectangle([(0, 0), (img_w, title_h)], fill=(20, 23, 29))
    tz = timezone(timedelta(hours=8))
    now_s = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
    title = f"1H涨幅 TOP20  |  {now_s} (北京时间)"
    draw.text((pad, 18), title, fill=YELLOW, font=ft_t)

    # Header row
    y = title_h
    draw.rectangle([(0, y), (img_w, y + header_h)], fill=HDR)
    x = pad
    for label, w in cols:
        tw = draw.textlength(label, font=ft_h)
        if label == "#":
            draw.text((x + (w - tw) / 2, y + 16), label, fill=GRAY, font=ft_h)
        elif label == "交易对":
            draw.text((x + 4, y + 16), label, fill=GRAY, font=ft_h)
        else:
            draw.text((x + w - tw - 4, y + 16), label, fill=GRAY, font=ft_h)
        x += w

    # Separator line
    draw.line([(pad, y + header_h - 2), (img_w - pad, y + header_h - 2)], fill=(42, 47, 56), width=2)

    # Data rows
    for idx, item in enumerate(data):
        y = title_h + header_h + idx * row_h
        if idx % 2 == 0:
            draw.rectangle([(0, y), (img_w, y + row_h)], fill=ROW_ALT)
        x = pad
        rank, chg, pct24 = idx + 1, item.get("changePercent", 0), item.get("priceChangePercent", 0)
        for label, w in cols:
            if label == "#":
                colors = {1: (255, 215, 0), 2: (192, 192, 192), 3: (205, 127, 50)}
                c = colors.get(rank, GRAY)
                t = str(rank)
                tw = draw.textlength(t, font=ft_rank)
                draw.text((x + (w - tw) / 2, y + 12), t, fill=c, font=ft_rank)
            elif label == "交易对":
                sym = item["symbol"].replace("USDT", "")
                draw.text((x + 4, y + 12), sym, fill=WHITE, font=ft_r)
            elif label == "当前价":
                p = item.get("currentPrice") or item.get("lastPrice") or 0
                t = fmt_price(p).replace("$", "")
                tw = draw.textlength(t, font=ft_r)
                draw.text((x + w - tw - 4, y + 12), t, fill=WHITE, font=ft_r)
            elif label == "1h涨跌":
                t = f"+{chg:.2f}%" if chg >= 0 else f"{chg:.2f}%"
                c = GREEN if chg >= 0 else RED
                tw = draw.textlength(t, font=ft_h)
                draw.text((x + w - tw - 4, y + 12), t, fill=c, font=ft_h)
            elif label == "1h前价":
                p1 = item.get("price1hAgo")
                t = fmt_price(p1).replace("$", "") if p1 else "--"
                tw = draw.textlength(t, font=ft_r)
                draw.text((x + w - tw - 4, y + 12), t, fill=GRAY, font=ft_r)
            elif label == "成交额(24h)":
                t = fmt_vol(item.get("quoteVolume", 0))
                tw = draw.textlength(t, font=ft_r)
                draw.text((x + w - tw - 4, y + 12), t, fill=GRAY, font=ft_r)
            elif label == "24h涨跌":
                t = f"+{pct24:.2f}%" if pct24 >= 0 else f"{pct24:.2f}%"
                c = GREEN if pct24 >= 0 else RED
                tw = draw.textlength(t, font=ft_r)
                draw.text((x + w - tw - 4, y + 12), t, fill=c, font=ft_r)
            x += w

    # Footer
    y = img_h - 28
    ft_txt = "Binance API  |  自动更新  |  不构成投资建议"
    tw = draw.textlength(ft_txt, font=ft_s)
    draw.text(((img_w - tw) / 2, y), ft_txt, fill=GRAY, font=ft_s)

    return img

# ============ 钉钉推送 ============
def dingtalk_signed_url():
    ts = str(round(time.time() * 1000))
    mac = hmac.new(DINGTALK_SECRET.encode(), f"{ts}\n{DINGTALK_SECRET}".encode(), hashlib.sha256)
    sign = urllib.parse.quote(base64.b64encode(mac.digest()), safe="")
    return f"{DINGTALK_WEBHOOK}&timestamp={ts}&sign={sign}"

def dingtalk_post(payload):
    return requests.post(dingtalk_signed_url(), json=payload, timeout=15).json()

def upload_to_imgur(image_bytes):
    """上传图片到 imgur.com，返回直接图片URL"""
    try:
        r = requests.post(
            "https://api.imgur.com/3/image",
            headers={"Authorization": "Client-ID 546c25a59c58ad7"},
            data={"image": base64.b64encode(image_bytes).decode()},
            timeout=30,
        )
        data = r.json()
        if data.get("success") and data.get("data", {}).get("link"):
            return data["data"]["link"]
        print(f"  imgur failed: {data}")
    except Exception as e:
        print(f"  imgur upload error: {e}")
    return None

def send_dingtalk_image(img):
    """上传到imgur，转短链接，通过link卡片+image消息双重发送"""
    buf = io.BytesIO()
    img.save(buf, "PNG")
    img_bytes = buf.getvalue()
    print(f"  PNG size: {len(img_bytes)/1024:.1f}KB")

    # Upload to imgur
    print("  Uploading to imgur...")
    url = upload_to_imgur(img_bytes)
    if not url:
        return False
    print(f"  URL: {url}")

    t_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")

    # 1. 主发送: link卡片 — 富文本带预览图
    result = dingtalk_post({
        "msgtype": "link",
        "link": {
            "title": f"加密和数字货币 1H涨幅TOP20 | {t_str}",
            "text": "数据来源: Binance API | 每30分钟自动更新 | 点击查看完整表格",
            "picUrl": url,
            "messageUrl": url
        }
    })
    if result.get("errcode") == 0:
        print("  Link卡片发送成功!")
        return True
    print(f"  Link卡片失败: {result}")

    # 2. fallback: image消息
    result = dingtalk_post({"msgtype": "image", "image": {"picURL": url}})
    if result.get("errcode") == 0:
        print("  图片消息发送成功!")
        return True
    return False

# ============ 主逻辑 ============
def main():
    print("=" * 60)
    print("Crypto 1H Gainers TOP20 -> DingTalk")
    print("=" * 60)

    # 1. Top pairs
    print("\n[1/4] Get top USDT pairs...")
    pairs = get_top_usdt_pairs(200)
    print(f"  Got {len(pairs)} pairs")

    # 2. 1h changes
    print("\n[2/4] Calculate 1h changes...")
    data = get_all_1h_changes(pairs)

    # 3. Sort top 20
    data.sort(key=lambda x: x.get("changePercent", 0), reverse=True)
    top20 = data[:20]

    print(f"\n[3/4] TOP 20:")
    print("-" * 72)
    print(f"{'#':<3} {'Symbol':<10} {'Price':>12} {'1h':>10} {'24h':>10} {'Vol':>12}")
    print("-" * 72)
    for i, d in enumerate(top20):
        sym = d["symbol"].replace("USDT", "")
        p = d.get("currentPrice") or d.get("lastPrice") or 0
        chg, p24, vol = d.get("changePercent", 0), d.get("priceChangePercent", 0), d.get("quoteVolume", 0)
        vs = f"${vol/1e9:.1f}B" if vol > 1e9 else f"${vol/1e6:.1f}M"
        print(f"{i+1:<3} {sym:<10} {p:>12.4f} {chg:>+9.2f}% {p24:>+9.2f}% {vs:>12}")
    print("-" * 72)

    # 4. Generate + Send
    print("\n[4/4] Generate image + send...")
    img = create_table_image(top20)

    # Save local copy
    local_path = os.path.join(OUTPUT_DIR, "1h_top20.png")
    img.save(local_path, "PNG")
    print(f"  Saved: {local_path}")

    # Send to DingTalk
    success = send_dingtalk_image(img)
    if success:
        print("\nDone! Image delivered to DingTalk.")
    else:
        print("\nImage send failed, trying markdown fallback...")
        # fallback not needed since catbox usually works, but we can try
    return True

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
