import json
import math
import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

LOCK = threading.Lock()

STATE = {
    "balance": 1000.0,
    "wagered": 0.0,
    "returned": 0.0,
    "bets": 0,
    "wins": 0,
    "history": [],
}

MINES = {
    "active": False,
    "bet": 0.0,
    "count": 0,
    "mine_set": set(),
    "revealed": set(),
}

ROULETTE = {
    "1": {"chance": 0.473, "payout": 2.0},
    "3": {"chance": 0.236, "payout": 4.0},
    "5": {"chance": 0.164, "payout": 6.0},
    "10": {"chance": 0.091, "payout": 11.0},
    "20": {"chance": 0.036, "payout": 21.0},
}

PLINKO = {
    "low": [10, 3, 1.6, 1.4, 1.1, 1, 0.5, 1, 1.1, 1.4, 1.6, 3, 10],
    "medium": [33, 11, 4, 2, 1.1, 0.6, 0.3, 0.6, 1.1, 2, 4, 11, 33],
    "high": [170, 24, 8.1, 2, 0.7, 0.2, 0.2, 0.2, 0.7, 2, 8.1, 24, 170],
}


def public_state():
    return {
        "balance": round(STATE["balance"], 2),
        "wagered": round(STATE["wagered"], 2),
        "returned": round(STATE["returned"], 2),
        "bets": STATE["bets"],
        "wins": STATE["wins"],
        "history": STATE["history"],
    }


def push_history(game, bet, delta, win, info):
    STATE["history"].insert(0, {
        "game": game,
        "bet": round(bet, 2),
        "delta": round(delta, 2),
        "win": bool(win),
        "info": info,
        "balance": round(STATE["balance"], 2),
    })
    del STATE["history"][60:]


def settle(game, bet, payout, win, info):
    STATE["balance"] += payout - bet
    STATE["wagered"] += bet
    STATE["returned"] += payout
    STATE["bets"] += 1
    if win:
        STATE["wins"] += 1
    push_history(game, bet, payout - bet, win, info)


def mine_mult(revealed, mines):
    if revealed <= 0:
        return 0.99
    return 0.99 * math.comb(25, revealed) / math.comb(25 - mines, revealed)


def public_mines():
    if not MINES["active"]:
        return {"active": False, "bet": 0, "count": 0, "revealed": [], "mult": 1.0, "next": 1.0}
    rev = sorted(MINES["revealed"])
    m = mine_mult(len(rev), MINES["count"])
    return {
        "active": True,
        "bet": round(MINES["bet"], 2),
        "count": MINES["count"],
        "revealed": rev,
        "mult": round(m, 4),
        "next": round(mine_mult(len(rev) + 1, MINES["count"]), 4),
    }


def do_spin(d):
    try:
        bet = float(d.get("bet", 0))
    except Exception:
        return {"error": "bad bet"}
    target = str(d.get("target", "1"))
    if target not in ROULETTE:
        return {"error": "bad target"}
    if bet <= 0 or bet > STATE["balance"]:
        return {"error": "bad bet"}
    cfg = ROULETTE[target]
    win = random.random() < cfg["chance"]
    payout = bet * cfg["payout"] if win else 0.0
    settle("Рулетка", bet, payout, win, "x" + target)
    return {"win": win, "payout": round(payout, 2), "target": target, "state": public_state()}


def do_coin(d):
    try:
        bet = float(d.get("bet", 0))
    except Exception:
        return {"error": "bad bet"}
    side = d.get("side", "heads")
    if side not in ("heads", "tails"):
        return {"error": "bad side"}
    if bet <= 0 or bet > STATE["balance"]:
        return {"error": "bad bet"}
    result = "heads" if random.random() < 0.5 else "tails"
    win = result == side
    payout = bet * 1.96 if win else 0.0
    settle("Монетка", bet, payout, win, result)
    return {"win": win, "payout": round(payout, 2), "result": result, "state": public_state()}


def do_dice(d):
    try:
        bet = float(d.get("bet", 0))
        threshold = int(d.get("threshold", 50))
    except Exception:
        return {"error": "bad input"}
    mode = d.get("mode", "under")
    if mode not in ("under", "over"):
        mode = "under"
    threshold = max(2, min(98, threshold))
    if bet <= 0 or bet > STATE["balance"]:
        return {"error": "bad bet"}
    roll = random.randint(0, 99)
    if mode == "under":
        chance = threshold / 100.0
        win = roll < threshold
    else:
        chance = (100 - threshold) / 100.0
        win = roll >= threshold
    mult = 0.99 / chance
    payout = bet * mult if win else 0.0
    settle("Кости", bet, payout, win, str(roll))
    return {
        "win": win, "payout": round(payout, 2), "roll": roll,
        "mult": round(mult, 4), "state": public_state()
    }


def do_plinko(d):
    try:
        bet = float(d.get("bet", 0))
    except Exception:
        return {"error": "bad bet"}
    risk = d.get("risk", "low")
    if risk not in PLINKO:
        risk = "low"
    if bet <= 0 or bet > STATE["balance"]:
        return {"error": "bad bet"}
    path = [random.randint(0, 1) for _ in range(12)]
    pos = sum(path)
    mult = PLINKO[risk][pos]
    payout = bet * mult
    win = payout > bet
    settle("Плинко", bet, payout, win, str(mult) + "x")
    return {
        "win": win, "payout": round(payout, 2), "path": path,
        "pos": pos, "mult": mult, "state": public_state()
    }


def do_mines_start(d):
    if MINES["active"]:
        return {"error": "game active"}
    try:
        bet = float(d.get("bet", 0))
        count = int(d.get("mines", 3))
    except Exception:
        return {"error": "bad input"}
    count = max(1, min(24, count))
    if bet <= 0 or bet > STATE["balance"]:
        return {"error": "bad bet"}
    STATE["balance"] -= bet
    STATE["wagered"] += bet
    STATE["bets"] += 1
    MINES["active"] = True
    MINES["bet"] = bet
    MINES["count"] = count
    MINES["mine_set"] = set(random.sample(range(25), count))
    MINES["revealed"] = set()
    return {"ok": True, "state": public_state(), "mines_state": public_mines()}


def do_mines_reveal(d):
    if not MINES["active"]:
        return {"error": "no game"}
    try:
        idx = int(d.get("index", -1))
    except Exception:
        return {"error": "bad index"}
    if idx < 0 or idx > 24 or idx in MINES["revealed"]:
        return {"error": "bad index"}
    if idx in MINES["mine_set"]:
        MINES["active"] = False
        MINES["revealed"].add(idx)
        push_history("Мины", MINES["bet"], -MINES["bet"], False, "мина")
        revealed_mines = sorted(MINES["mine_set"])
        bet = MINES["bet"]
        MINES["mine_set"] = set()
        MINES["revealed"] = set()
        MINES["bet"] = 0.0
        MINES["count"] = 0
        return {
            "lost": True, "mines": revealed_mines, "bet": bet,
            "state": public_state(), "mines_state": public_mines()
        }
    MINES["revealed"].add(idx)
    return {"lost": False, "state": public_state(), "mines_state": public_mines()}


def do_mines_cashout(d):
    if not MINES["active"]:
        return {"error": "no game"}
    if not MINES["revealed"]:
        return {"error": "nothing revealed"}
    mult = mine_mult(len(MINES["revealed"]), MINES["count"])
    bet = MINES["bet"]
    payout = bet * mult
    STATE["balance"] += payout
    STATE["returned"] += payout
    STATE["wins"] += 1
    push_history("Мины", bet, payout - bet, True, str(round(mult, 2)) + "x")
    MINES["active"] = False
    MINES["mine_set"] = set()
    MINES["revealed"] = set()
    MINES["bet"] = 0.0
    MINES["count"] = 0
    return {
        "ok": True, "payout": round(payout, 2), "mult": round(mult, 4),
        "state": public_state(), "mines_state": public_mines()
    }


def do_reset(d):
    STATE["balance"] = 1000.0
    STATE["wagered"] = 0.0
    STATE["returned"] = 0.0
    STATE["bets"] = 0
    STATE["wins"] = 0
    STATE["history"] = []
    MINES["active"] = False
    MINES["bet"] = 0.0
    MINES["count"] = 0
    MINES["mine_set"] = set()
    MINES["revealed"] = set()
    return {"ok": True, "state": public_state(), "mines_state": public_mines()}


ROUTES = {
    "/api/spin": do_spin,
    "/api/coin": do_coin,
    "/api/dice": do_dice,
    "/api/plinko": do_plinko,
    "/api/mines/start": do_mines_start,
    "/api/mines/reveal": do_mines_reveal,
    "/api/mines/cashout": do_mines_cashout,
    "/api/reset": do_reset,
}

HTML = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FAKE CASINO</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0b0d12;color:#e7e9ee;min-height:100vh;-webkit-font-smoothing:antialiased}
header{display:flex;justify-content:space-between;align-items:center;padding:14px 20px;background:#11141b;border-bottom:1px solid #1e2430;flex-wrap:wrap;gap:12px;position:sticky;top:0;z-index:20}
.brand{font-weight:900;letter-spacing:3px;background:linear-gradient(90deg,#ff4d6d,#ffb84d);-webkit-background-clip:text;background-clip:text;color:transparent;font-size:17px}
.stats{display:flex;gap:20px;flex-wrap:wrap}
.stat{display:flex;flex-direction:column;font-size:10px;color:#7b8494;text-transform:uppercase;letter-spacing:1.2px}
.stat b{font-size:16px;color:#fff;font-variant-numeric:tabular-nums;margin-top:2px}
.stat b.good{color:#4ade80}
.stat b.bad{color:#f87171}
nav{display:flex;gap:6px;padding:10px 20px;overflow-x:auto;background:#0e1117;border-bottom:1px solid #1e2430;position:sticky;top:61px;z-index:19}
nav::-webkit-scrollbar{height:0}
nav button{background:transparent;border:1px solid transparent;color:#8b95a7;padding:8px 15px;border-radius:9px;cursor:pointer;font-size:13px;font-weight:600;white-space:nowrap;transition:.15s;font-family:inherit}
nav button:hover{color:#fff;background:#161b24}
nav button.active{color:#fff;background:#1c2230;border-color:#2b3548}
main{padding:20px;max-width:1020px;margin:0 auto}
.tab{display:none}
.tab.active{display:block;animation:fade .25s ease}
@keyframes fade{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.panel{background:#11141b;border:1px solid #1e2430;border-radius:14px;padding:18px;margin-bottom:14px}
.panel h3{font-size:12px;text-transform:uppercase;letter-spacing:1.4px;color:#7b8494;margin-bottom:14px;font-weight:700}
.row{display:flex;align-items:center;gap:12px;margin-bottom:14px;flex-wrap:wrap}
.row>label{font-size:12px;text-transform:uppercase;letter-spacing:1px;color:#7b8494;min-width:60px;font-weight:700}
input[type=number]{background:#0b0d12;border:1px solid #2b3548;color:#fff;padding:10px 12px;border-radius:9px;font-size:15px;width:140px;font-family:inherit;font-variant-numeric:tabular-nums}
input[type=number]:focus{outline:none;border-color:#ff4d6d}
input[type=range]{width:100%;accent-color:#ff4d6d}
.choices{display:flex;gap:6px;flex-wrap:wrap}
.choices button{background:#161b24;border:1px solid #2b3548;color:#a8b2c4;padding:8px 16px;border-radius:9px;cursor:pointer;font-weight:700;font-size:13px;transition:.15s;font-family:inherit}
.choices button:hover{color:#fff;border-color:#3d4a63}
.choices button.active{background:#ff4d6d;border-color:#ff4d6d;color:#fff}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}
.chips button{background:#161b24;border:1px solid #2b3548;color:#a8b2c4;padding:7px 13px;border-radius:8px;cursor:pointer;font-weight:700;font-size:12px;transition:.15s;font-family:inherit}
.chips button:hover{color:#fff;border-color:#ff4d6d;background:#1c2230}
.action{width:100%;padding:15px;border:none;border-radius:11px;background:linear-gradient(90deg,#ff4d6d,#ff7a4d);color:#fff;font-weight:900;font-size:15px;letter-spacing:1.5px;cursor:pointer;transition:.15s;font-family:inherit;text-transform:uppercase}
.action:hover{filter:brightness(1.1);transform:translateY(-1px)}
.action:active{transform:translateY(0)}
.action:disabled{opacity:.5;cursor:not-allowed;transform:none;filter:none}
.msg{margin-top:14px;padding:13px;border-radius:10px;font-weight:700;text-align:center;font-size:14px;min-height:46px;display:flex;align-items:center;justify-content:center;background:#0b0d12;border:1px solid #1e2430;color:#7b8494}
.msg.win{background:rgba(74,222,128,.1);border-color:rgba(74,222,128,.4);color:#4ade80}
.msg.lose{background:rgba(248,113,113,.1);border-color:rgba(248,113,113,.4);color:#f87171}
.stripWrap{position:relative;overflow:hidden;height:92px;background:#0b0d12;border:1px solid #1e2430;border-radius:11px;margin-bottom:6px}
.strip{display:flex;height:100%;align-items:center;will-change:transform}
.strip .cell{flex:0 0 70px;height:70px;margin:0 1px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:15px;color:#fff}
.strip .m1{background:#2b3548}
.strip .m3{background:#2563eb}
.strip .m5{background:#7c3aed}
.strip .m10{background:#db2777}
.strip .m20{background:#f59e0b;color:#1a1a1a}
.needle{position:absolute;top:0;bottom:0;left:50%;width:3px;background:#ff4d6d;transform:translateX(-50%);box-shadow:0 0 14px #ff4d6d;pointer-events:none;z-index:2}
.coin{width:150px;height:150px;border-radius:50%;background:linear-gradient(145deg,#ffb84d,#d97706);display:flex;align-items:center;justify-content:center;font-size:56px;font-weight:900;color:#1a1a1a;margin:0 auto 22px;transition:transform .6s cubic-bezier(.2,.8,.3,1);box-shadow:0 10px 40px rgba(255,184,77,.25)}
.coin.flip{animation:coinflip .7s ease}
@keyframes coinflip{0%{transform:rotateY(0) scale(1)}50%{transform:rotateY(900deg) scale(1.15)}100%{transform:rotateY(1800deg) scale(1)}}
.dice-num{font-size:64px;font-weight:900;text-align:center;font-variant-numeric:tabular-nums;margin-bottom:8px;letter-spacing:-2px}
.dice-num.win{color:#4ade80}
.dice-num.lose{color:#f87171}
.minesGrid{display:grid;grid-template-columns:repeat(5,1fr);gap:9px;max-width:400px;margin:0 auto 18px}
.minesGrid button{aspect-ratio:1;border:1px solid #2b3548;background:#161b24;border-radius:11px;font-size:24px;cursor:pointer;transition:.15s;color:#fff;font-family:inherit}
.minesGrid button:hover:not(:disabled){background:#1c2230;border-color:#3d4a63;transform:scale(1.04)}
.minesGrid button:disabled{cursor:default}
.minesGrid button.gem{background:rgba(74,222,128,.15);border-color:#4ade80}
.minesGrid button.mine{background:rgba(248,113,113,.2);border-color:#f87171}
canvas{display:block;width:100%;max-width:700px;margin:0 auto;border-radius:11px;background:#0b0d12}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:9px;color:#7b8494;font-size:10px;text-transform:uppercase;letter-spacing:1.2px;border-bottom:1px solid #1e2430;font-weight:700}
td{padding:9px;border-bottom:1px solid #161b24;font-variant-numeric:tabular-nums}
td.pos{color:#4ade80;font-weight:700}
td.neg{color:#f87171;font-weight:700}
.badge{display:inline-block;padding:2px 8px;border-radius:6px;font-size:11px;font-weight:700;background:#1c2230;color:#a8b2c4}
.footnote{text-align:center;font-size:11px;color:#4a5364;padding:20px;line-height:1.7}
.empty{text-align:center;padding:40px;color:#4a5364;font-size:13px}
@media(max-width:600px){header{padding:12px 14px}main{padding:14px}nav{padding:8px 14px;top:auto;position:static}.stat b{font-size:14px}.dice-num{font-size:48px}}
</style>
</head>
<body>

<header>
  <div class="brand">FAKE CASINO</div>
  <div class="stats">
    <div class="stat"><span>Баланс</span><b id="balance">1000</b></div>
    <div class="stat"><span>Поставлено</span><b id="wagered">0</b></div>
    <div class="stat"><span>Возврат</span><b id="rtp">—</b></div>
    <div class="stat"><span>Спинов</span><b id="bets">0</b></div>
  </div>
</header>

<nav>
  <button data-tab="roulette" class="active">Рулетка</button>
  <button data-tab="coin">Монетка</button>
  <button data-tab="dice">Кости</button>
  <button data-tab="plinko">Плинко</button>
  <button data-tab="mines">Мины</button>
  <button data-tab="stats">Статистика</button>
</nav>

<main>

<section id="tab-roulette" class="tab active">
  <div class="panel">
    <div class="stripWrap" id="stripWrap">
      <div class="strip" id="strip"></div>
      <div class="needle"></div>
    </div>
  </div>
  <div class="panel">
    <div class="row">
      <label>Цель</label>
      <div class="choices" id="rTarget">
        <button data-v="1" class="active">x1 · 47%</button>
        <button data-v="3">x3 · 24%</button>
        <button data-v="5">x5 · 16%</button>
        <button data-v="10">x10 · 9%</button>
        <button data-v="20">x20 · 3.6%</button>
      </div>
    </div>
    <div class="row">
      <label>Ставка</label>
      <input type="number" id="rBet" value="100" min="1">
    </div>
    <div class="chips">
      <button data-bet="rBet" data-add="10">+10</button>
      <button data-bet="rBet" data-add="50">+50</button>
      <button data-bet="rBet" data-add="100">+100</button>
      <button data-bet="rBet" data-add="500">+500</button>
      <button data-bet="rBet" data-mul="0.5">½</button>
      <button data-bet="rBet" data-mul="2">×2</button>
      <button data-bet="rBet" data-max="1">MAX</button>
    </div>
    <button class="action" id="rSpin">Крутить</button>
    <div class="msg" id="rMsg">Выбери цель и ставку</div>
  </div>
</section>

<section id="tab-coin" class="tab">
  <div class="panel">
    <div class="coin" id="coin">?</div>
    <div class="choices" id="cSide" style="justify-content:center">
      <button data-v="heads" class="active">Орёл</button>
      <button data-v="tails">Решка</button>
    </div>
  </div>
  <div class="panel">
    <div class="row">
      <label>Ставка</label>
      <input type="number" id="cBet" value="100" min="1">
    </div>
    <div class="chips">
      <button data-bet="cBet" data-add="10">+10</button>
      <button data-bet="cBet" data-add="50">+50</button>
      <button data-bet="cBet" data-add="100">+100</button>
      <button data-bet="cBet" data-add="500">+500</button>
      <button data-bet="cBet" data-mul="0.5">½</button>
      <button data-bet="cBet" data-mul="2">×2</button>
      <button data-bet="cBet" data-max="1">MAX</button>
    </div>
    <button class="action" id="cFlip">Подбросить</button>
    <div class="msg" id="cMsg">Шанс 50% · выплата ×1.96</div>
  </div>
</section>

<section id="tab-dice" class="tab">
  <div class="panel">
    <div class="dice-num" id="dNum">—</div>
    <div class="choices" id="dMode" style="justify-content:center">
      <button data-v="under" class="active">Меньше</button>
      <button data-v="over">Больше</button>
    </div>
  </div>
  <div class="panel">
    <div class="row" style="display:block">
      <label style="display:block;margin-bottom:10px">Порог: <span id="dThVal">50</span></label>
      <input type="range" id="dTh" min="2" max="98" value="50">
    </div>
    <div class="row">
      <label>Шанс</label>
      <b id="dChance" style="font-size:15px">50.00%</b>
      <label style="margin-left:16px">Выплата</label>
      <b id="dMult" style="font-size:15px">×1.98</b>
    </div>
    <div class="row">
      <label>Ставка</label>
      <input type="number" id="dBet" value="100" min="1">
    </div>
    <div class="chips">
      <button data-bet="dBet" data-add="10">+10</button>
      <button data-bet="dBet" data-add="50">+50</button>
      <button data-bet="dBet" data-add="100">+100</button>
      <button data-bet="dBet" data-add="500">+500</button>
      <button data-bet="dBet" data-mul="0.5">½</button>
      <button data-bet="dBet" data-mul="2">×2</button>
      <button data-bet="dBet" data-max="1">MAX</button>
    </div>
    <button class="action" id="dRoll">Бросок</button>
    <div class="msg" id="dMsg">Крути порог и жми</div>
  </div>
</section>

<section id="tab-plinko" class="tab">
  <div class="panel">
    <canvas id="plinkoCanvas" width="700" height="440"></canvas>
  </div>
  <div class="panel">
    <div class="row">
      <label>Риск</label>
      <div class="choices" id="pRisk">
        <button data-v="low" class="active">Низкий</button>
        <button data-v="medium">Средний</button>
        <button data-v="high">Высокий</button>
      </div>
    </div>
    <div class="row">
      <label>Ставка</label>
      <input type="number" id="pBet" value="100" min="1">
    </div>
    <div class="chips">
      <button data-bet="pBet" data-add="10">+10</button>
      <button data-bet="pBet" data-add="50">+50</button>
      <button data-bet="pBet" data-add="100">+100</button>
      <button data-bet="pBet" data-add="500">+500</button>
      <button data-bet="pBet" data-mul="0.5">½</button>
      <button data-bet="pBet" data-mul="2">×2</button>
      <button data-bet="pBet" data-max="1">MAX</button>
    </div>
    <button class="action" id="pDrop">Бросить шар</button>
    <div class="msg" id="pMsg">12 рядов · 13 лунок</div>
  </div>
</section>

<section id="tab-mines" class="tab">
  <div class="panel">
    <div class="minesGrid" id="mGrid"></div>
    <div class="row" style="justify-content:center;gap:24px">
      <div style="text-align:center"><div style="font-size:10px;color:#7b8494;text-transform:uppercase;letter-spacing:1px">Множитель</div><b id="mMult" style="font-size:20px">1.00×</b></div>
      <div style="text-align:center"><div style="font-size:10px;color:#7b8494;text-transform:uppercase;letter-spacing:1px">Следующий</div><b id="mNext" style="font-size:20px;color:#4ade80">1.13×</b></div>
    </div>
  </div>
  <div class="panel">
    <div class="row">
      <label>Мин</label>
      <div class="choices" id="mCount">
        <button data-v="1">1</button>
        <button data-v="3" class="active">3</button>
        <button data-v="5">5</button>
        <button data-v="10">10</button>
        <button data-v="24">24</button>
      </div>
    </div>
    <div class="row">
      <label>Ставка</label>
      <input type="number" id="mBet" value="100" min="1">
    </div>
    <div class="chips">
      <button data-bet="mBet" data-add="10">+10</button>
      <button data-bet="mBet" data-add="50">+50</button>
      <button data-bet="mBet" data-add="100">+100</button>
      <button data-bet="mBet" data-add="500">+500</button>
      <button data-bet="mBet" data-mul="0.5">½</button>
      <button data-bet="mBet" data-mul="2">×2</button>
      <button data-bet="mBet" data-max="1">MAX</button>
    </div>
    <button class="action" id="mStart">Начать игру</button>
    <button class="action" id="mCash" style="margin-top:8px;background:linear-gradient(90deg,#22c55e,#4ade80);display:none">Забрать</button>
    <div class="msg" id="mMsg">Выбери количество мин и жми «Начать»</div>
  </div>
</section>

<section id="tab-stats" class="tab">
  <div class="panel">
    <h3>Сессия</h3>
    <table>
      <tr><td>Баланс</td><td id="sBal" style="text-align:right"></td></tr>
      <tr><td>Всего поставлено</td><td id="sWag" style="text-align:right"></td></tr>
      <tr><td>Всего возвращено</td><td id="sRet" style="text-align:right"></td></tr>
      <tr><td>Фактический возврат (RTP)</td><td id="sRtp" style="text-align:right"></td></tr>
      <tr><td>Спинов / ставок</td><td id="sBets" style="text-align:right"></td></tr>
      <tr><td>Побед</td><td id="sWins" style="text-align:right"></td></tr>
      <tr><td>Профит</td><td id="sProfit" style="text-align:right"></td></tr>
    </table>
  </div>
  <div class="panel">
    <h3>История (последние 60)</h3>
    <div id="sHist"></div>
  </div>
  <div class="panel">
    <button class="action" id="sReset" style="background:linear-gradient(90deg,#475569,#64748b)">Сбросить баланс до 1000</button>
  </div>
  <div class="footnote">
    Возврат в игре всегда меньше 100%. На длинной дистанции это всегда минус.<br>
    Никакая стратегия «догона» это не обходит — только откладывает.
  </div>
</section>

</main>

<script>
let S = {};

async function api(path, body){
  const r = await fetch(path, {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(body || {})
  });
  return r.json();
}

function fmt(n){
  return (Math.round(n * 100) / 100).toLocaleString('ru-RU');
}

function render(){
  document.getElementById('balance').textContent = fmt(S.balance);
  document.getElementById('wagered').textContent = fmt(S.wagered);
  document.getElementById('bets').textContent = S.bets;
  const rtp = S.wagered > 0 ? (S.returned / S.wagered * 100) : null;
  const rtpEl = document.getElementById('rtp');
  if (rtp === null){
    rtpEl.textContent = '—';
    rtpEl.className = '';
  } else {
    rtpEl.textContent = rtp.toFixed(1) + '%';
    rtpEl.className = rtp >= 100 ? 'good' : 'bad';
  }
  const profit = S.balance - 1000;
  const profitEl = document.getElementById('sProfit');
  profitEl.textContent = (profit >= 0 ? '+' : '') + fmt(profit);
  profitEl.className = profit >= 0 ? 'pos' : 'neg';
  document.getElementById('sBal').textContent = fmt(S.balance);
  document.getElementById('sWag').textContent = fmt(S.wagered);
  document.getElementById('sRet').textContent = fmt(S.returned);
  document.getElementById('sRtp').textContent = rtp === null ? '—' : rtp.toFixed(2) + '%';
  document.getElementById('sBets').textContent = S.bets;
  document.getElementById('sWins').textContent = S.wins;

  const h = document.getElementById('sHist');
  if (!S.history.length){
    h.innerHTML = '<div class="empty">Пока пусто. Сделай ставку.</div>';
  } else {
    let html = '<table><tr><th>Игра</th><th>Инфо</th><th>Ставка</th><th>Итог</th><th style="text-align:right">Баланс</th></tr>';
    for (const e of S.history){
      html += '<tr><td><span class="badge">' + e.game + '</span></td><td>' + e.info + '</td><td>' + fmt(e.bet) + '</td><td class="' + (e.win ? 'pos' : 'neg') + '">' + (e.delta >= 0 ? '+' : '') + fmt(e.delta) + '</td><td style="text-align:right">' + fmt(e.balance) + '</td></tr>';
    }
    html += '</table>';
    h.innerHTML = html;
  }
}

async function refresh(){
  const r = await fetch('/api/state');
  S = await r.json();
  render();
}

function getBet(id){
  return parseFloat(document.getElementById(id).value) || 0;
}

function setBet(id, v){
  document.getElementById(id).value = Math.max(1, Math.floor(v));
}

document.querySelectorAll('.chips button').forEach(b => {
  b.addEventListener('click', () => {
    const id = b.dataset.bet;
    let v = getBet(id);
    if (b.dataset.add) v += parseFloat(b.dataset.add);
    if (b.dataset.mul) v *= parseFloat(b.dataset.mul);
    if (b.dataset.max) v = S.balance;
    setBet(id, v);
  });
});

document.querySelectorAll('nav button').forEach(b => {
  b.addEventListener('click', () => {
    document.querySelectorAll('nav button').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    document.getElementById('tab-' + b.dataset.tab).classList.add('active');
    if (b.dataset.tab === 'plinko') drawPlinko();
  });
});

function choiceGroup(id, cb){
  const g = document.getElementById(id);
  g.querySelectorAll('button').forEach(b => {
    b.addEventListener('click', () => {
      g.querySelectorAll('button').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      if (cb) cb(b.dataset.v);
    });
  });
}

function selected(id){
  const el = document.querySelector('#' + id + ' button.active');
  return el ? el.dataset.v : null;
}

/* ---- ROULETTE ---- */
let rTarget = '1';
let rBusy = false;
choiceGroup('rTarget', v => { rTarget = v; });

const POOL = [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
              3,3,3,3,3,3,3,3,3,3,3,3,3,3,
              5,5,5,5,5,5,5,5,5,5,
              10,10,10,10,10,
              20,20];

function buildStrip(target){
  const strip = document.getElementById('strip');
  strip.innerHTML = '';
  strip.style.transition = 'none';
  strip.style.transform = 'translateX(0)';
  for (let i = 0; i < 60; i++){
    const v = (i === 55) ? parseInt(target) : POOL[Math.floor(Math.random() * POOL.length)];
    const d = document.createElement('div');
    d.className = 'cell m' + v;
    d.textContent = 'x' + v;
    strip.appendChild(d);
  }
}

document.getElementById('rSpin').addEventListener('click', async () => {
  if (rBusy) return;
  const bet = getBet('rBet');
  if (bet <= 0){ document.getElementById('rMsg').textContent = 'Ставка > 0'; return; }
  if (bet > S.balance){ document.getElementById('rMsg').textContent = 'Недостаточно монет'; return; }
  rBusy = true;
  const btn = document.getElementById('rSpin');
  btn.disabled = true;
  const msg = document.getElementById('rMsg');
  msg.className = 'msg';
  msg.textContent = 'Крутится...';

  const res = await api('/api/spin', {bet: bet, target: rTarget});
  if (res.error){
    msg.textContent = res.error;
    rBusy = false;
    btn.disabled = false;
    return;
  }

  buildStrip(rTarget);
  const strip = document.getElementById('strip');
  const wrap = document.getElementById('stripWrap');
  const cw = 72;
  const offset = 55 * cw + 35 - wrap.clientWidth / 2;
  void strip.offsetWidth;
  strip.style.transition = 'transform 4s cubic-bezier(.15,.85,.25,1)';
  strip.style.transform = 'translateX(' + (-offset) + 'px)';

  setTimeout(() => {
    S = res.state;
    render();
    if (res.win){
      msg.className = 'msg win';
      msg.textContent = 'ВЫИГРЫШ x' + res.target + ' → +' + fmt(res.payout - bet);
    } else {
      msg.className = 'msg lose';
      msg.textContent = 'Проигрыш −' + fmt(bet);
    }
    rBusy = false;
    btn.disabled = false;
  }, 4100);
});

/* ---- COIN ---- */
let cSide = 'heads';
choiceGroup('cSide', v => { cSide = v; });

document.getElementById('cFlip').addEventListener('click', async () => {
  const bet = getBet('cBet');
  const msg = document.getElementById('cMsg');
  if (bet <= 0 || bet > S.balance){ msg.className = 'msg lose'; msg.textContent = 'Проверь ставку'; return; }
  const coin = document.getElementById('coin');
  coin.classList.remove('flip');
  void coin.offsetWidth;
  coin.classList.add('flip');
  const res = await api('/api/coin', {bet: bet, side: cSide});
  if (res.error){ msg.textContent = res.error; return; }
  setTimeout(() => {
    coin.textContent = res.result === 'heads' ? 'О' : 'Р';
    S = res.state;
    render();
    if (res.win){
      msg.className = 'msg win';
      msg.textContent = 'Угадал! +' + fmt(res.payout - bet);
    } else {
      msg.className = 'msg lose';
      msg.textContent = 'Мимо. −' + fmt(bet);
    }
  }, 700);
});

/* ---- DICE ---- */
let dMode = 'under';
choiceGroup('dMode', v => { dMode = v; updateDiceInfo(); });

function updateDiceInfo(){
  const th = parseInt(document.getElementById('dTh').value);
  document.getElementById('dThVal').textContent = th;
  const chance = dMode === 'under' ? th / 100 : (100 - th) / 100;
  const mult = 0.99 / chance;
  document.getElementById('dChance').textContent = (chance * 100).toFixed(2) + '%';
  document.getElementById('dMult').textContent = '×' + mult.toFixed(2);
}
document.getElementById('dTh').addEventListener('input', updateDiceInfo);
updateDiceInfo();

document.getElementById('dRoll').addEventListener('click', async () => {
  const bet = getBet('dBet');
  const msg = document.getElementById('dMsg');
  const th = parseInt(document.getElementById('dTh').value);
  if (bet <= 0 || bet > S.balance){ msg.className = 'msg lose'; msg.textContent = 'Проверь ставку'; return; }
  const res = await api('/api/dice', {bet: bet, mode: dMode, threshold: th});
  if (res.error){ msg.textContent = res.error; return; }
  const el = document.getElementById('dNum');
  el.textContent = res.roll;
  el.className = 'dice-num ' + (res.win ? 'win' : 'lose');
  S = res.state;
  render();
  if (res.win){
    msg.className = 'msg win';
    msg.textContent = 'Выпало ' + res.roll + ' → +' + fmt(res.payout - bet);
  } else {
    msg.className = 'msg lose';
    msg.textContent = 'Выпало ' + res.roll + ' → −' + fmt(bet);
  }
});

/* ---- PLINKO ---- */
let pRisk = 'low';
choiceGroup('pRisk', v => { pRisk = v; drawPlinko(); });

const ROWS = 12;

function drawPlinko(ball, hitIndex){
  const c = document.getElementById('plinkoCanvas');
  const ctx = c.getContext('2d');
  const W = c.width, H = c.height;
  const s = W / 14;
  const rowGap = (H - 80) / (ROWS + 1);
  ctx.clearRect(0, 0, W, H);

  for (let r = 0; r < ROWS; r++){
    for (let j = 0; j <= r + 1; j++){
      const x = W / 2 + (j - (r + 1) / 2) * s;
      const y = 22 + r * rowGap;
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fillStyle = '#2b3548';
      ctx.fill();
    }
  }

  const table = {low:[10,3,1.6,1.4,1.1,1,0.5,1,1.1,1.4,1.6,3,10],
                 medium:[33,11,4,2,1.1,0.6,0.3,0.6,1.1,2,4,11,33],
                 high:[170,24,8.1,2,0.7,0.2,0.2,0.2,0.7,2,8.1,24,170]}[pRisk];
  const by = 22 + ROWS * rowGap + 14;
  for (let g = 0; g < 13; g++){
    const x = W / 2 + (g - 6) * s;
    const w = s * 0.9;
    ctx.fillStyle = (hitIndex === g) ? '#ff4d6d' : '#161b24';
    ctx.strokeStyle = '#2b3548';
    ctx.lineWidth = 1;
    const rr = 5;
    ctx.beginPath();
    ctx.moveTo(x - w / 2 + rr, by);
    ctx.lineTo(x + w / 2 - rr, by);
    ctx.quadraticCurveTo(x + w / 2, by, x + w / 2, by + rr);
    ctx.lineTo(x + w / 2, by + 26 - rr);
    ctx.quadraticCurveTo(x + w / 2, by + 26, x + w / 2 - rr, by + 26);
    ctx.lineTo(x - w / 2 + rr, by + 26);
    ctx.quadraticCurveTo(x - w / 2, by + 26, x - w / 2, by + 26 - rr);
    ctx.lineTo(x - w / 2, by + rr);
    ctx.quadraticCurveTo(x - w / 2, by, x - w / 2 + rr, by);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = (hitIndex === g) ? '#fff' : '#7b8494';
    ctx.font = 'bold 10px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(table[g] + 'x', x, by + 17);
  }

  if (ball){
    ctx.beginPath();
    ctx.arc(ball.x, ball.y, 7, 0, Math.PI * 2);
    ctx.fillStyle = '#ff4d6d';
    ctx.shadowColor = '#ff4d6d';
    ctx.shadowBlur = 14;
    ctx.fill();
    ctx.shadowBlur = 0;
  }
}

function animateBall(path, onDone){
  const c = document.getElementById('plinkoCanvas');
  const W = c.width, H = c.height;
  const s = W / 14;
  const rowGap = (H - 80) / (ROWS + 1);
  let o = 0;
  const pts = [{x: W / 2, y: 10}];
  for (let r = 0; r < ROWS; r++){
    o += path[r];
    pts.push({x: W / 2 + (o - (r + 1) / 2) * s, y: 22 + (r + 1) * rowGap});
  }
  let seg = 0, t = 0;
  const speed = 0.045;
  function frame(){
    t += speed;
    while (t >= 1 && seg < pts.length - 1){ t -= 1; seg++; }
    if (seg >= pts.length - 1){
      const last = pts[pts.length - 1];
      drawPlinko({x: last.x, y: last.y}, o);
      onDone();
      return;
    }
    const a = pts[seg], b = pts[seg + 1];
    const x = a.x + (b.x - a.x) * t;
    const y = a.y + (b.y - a.y) * (t * t * 0.6 + t * 0.4);
    drawPlinko({x: x, y: y});
    requestAnimationFrame(frame);
  }
  frame();
}

let pBusy = false;
document.getElementById('pDrop').addEventListener('click', async () => {
  if (pBusy) return;
  const bet = getBet('pBet');
  const msg = document.getElementById('pMsg');
  if (bet <= 0 || bet > S.balance){ msg.className = 'msg lose'; msg.textContent = 'Проверь ставку'; return; }
  pBusy = true;
  document.getElementById('pDrop').disabled = true;
  msg.className = 'msg';
  msg.textContent = 'Летит...';
  const res = await api('/api/plinko', {bet: bet, risk: pRisk});
  if (res.error){ msg.textContent = res.error; pBusy = false; document.getElementById('pDrop').disabled = false; return; }
  animateBall(res.path, () => {
    S = res.state;
    render();
    if (res.win){
      msg.className = 'msg win';
      msg.textContent = 'Лунка ' + res.mult + 'x → +' + fmt(res.payout - bet);
    } else {
      msg.className = 'msg lose';
      msg.textContent = 'Лунка ' + res.mult + 'x → −' + fmt(bet - res.payout);
    }
    pBusy = false;
    document.getElementById('pDrop').disabled = false;
  });
});

/* ---- MINES ---- */
let mCount = 3;
let mActive = false;
choiceGroup('mCount', v => { mCount = parseInt(v); });

function buildGrid(){
  const g = document.getElementById('mGrid');
  g.innerHTML = '';
  for (let i = 0; i < 25; i++){
    const b = document.createElement('button');
    b.dataset.i = i;
    b.textContent = '';
    b.addEventListener('click', () => revealCell(i, b));
    g.appendChild(b);
  }
}

async function revealCell(i, btn){
  if (!mActive || btn.disabled) return;
  const res = await api('/api/mines/reveal', {index: i});
  if (res.error) return;
  const msg = document.getElementById('mMsg');
  if (res.lost){
    const cells = document.querySelectorAll('#mGrid button');
    cells.forEach((c, idx) => {
      c.disabled = true;
      if (res.mines.includes(idx)){
        c.classList.add('mine');
        c.textContent = '💣';
      } else if (idx === i){
        c.classList.add('mine');
        c.textContent = '💥';
      }
    });
    S = res.state;
    render();
    msg.className = 'msg lose';
    msg.textContent = 'Мина! Потеряно ' + fmt(res.bet);
    mActive = false;
    document.getElementById('mStart').style.display = '';
    document.getElementById('mCash').style.display = 'none';
    document.getElementById('mMult').textContent = '1.00×';
    document.getElementById('mNext').textContent = '1.13×';
    return;
  }
  btn.classList.add('gem');
  btn.textContent = '💎';
  btn.disabled = true;
  S = res.state;
  render();
  const ms = res.mines_state;
  document.getElementById('mMult').textContent = ms.mult.toFixed(2) + '×';
  document.getElementById('mNext').textContent = ms.next.toFixed(2) + '×';
  msg.className = 'msg';
  msg.textContent = 'Открыто: ' + ms.revealed.length + ' · текущий множитель ' + ms.mult.toFixed(2) + '×';
}

document.getElementById('mStart').addEventListener('click', async () => {
  const bet = getBet('mBet');
  const msg = document.getElementById('mMsg');
  if (bet <= 0 || bet > S.balance){ msg.className = 'msg lose'; msg.textContent = 'Проверь ставку'; return; }
  const res = await api('/api/mines/start', {bet: bet, mines: mCount});
  if (res.error){ msg.className = 'msg lose'; msg.textContent = res.error; return; }
  mActive = true;
  S = res.state;
  render();
  buildGrid();
  document.getElementById('mStart').style.display = 'none';
  document.getElementById('mCash').style.display = '';
  document.getElementById('mMult').textContent = '1.00×';
  const ms = res.mines_state;
  document.getElementById('mNext').textContent = ms.next.toFixed(2) + '×';
  msg.className = 'msg';
  msg.textContent = 'Игра началась. Открывай клетки или забирай.';
});

document.getElementById('mCash').addEventListener('click', async () => {
  const msg = document.getElementById('mMsg');
  const res = await api('/api/mines/cashout', {});
  if (res.error){ msg.className = 'msg lose'; msg.textContent = 'Открой хотя бы одну клетку'; return; }
  mActive = false;
  S = res.state;
  render();
  document.querySelectorAll('#mGrid button').forEach(c => c.disabled = true);
  document.getElementById('mStart').style.display = '';
  document.getElementById('mCash').style.display = 'none';
  document.getElementById('mMult').textContent = '1.00×';
  document.getElementById('mNext').textContent = '1.13×';
  msg.className = 'msg win';
  msg.textContent = 'Забрал ' + fmt(res.payout) + ' (' + res.mult.toFixed(2) + '×)';
});

/* ---- RESET ---- */
document.getElementById('sReset').addEventListener('click', async () => {
  const res = await api('/api/reset', {});
  S = res.state;
  render();
  mActive = false;
  buildGrid();
  document.getElementById('mStart').style.display = '';
  document.getElementById('mCash').style.display = 'none';
  document.getElementById('mMsg').className = 'msg';
  document.getElementById('mMsg').textContent = 'Выбери количество мин и жми «Начать»';
});

/* ---- INIT ---- */
buildGrid();
drawPlinko();
refresh();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            self._send(200, HTML, "text/html; charset=utf-8")
        elif path == "/api/state":
            with LOCK:
                self._json({"state": public_state(), "mines_state": public_mines()})
        elif path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        else:
            self._send(404, "not found", "text/plain; charset=utf-8")

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            data = {}
        fn = ROUTES.get(path)
        if not fn:
            self._json({"error": "unknown route"}, 404)
            return
        with LOCK:
            try:
                result = fn(data)
            except Exception as e:
                result = {"error": str(e)}
        self._json(result)


def main():
    port = 8000
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("Fake casino running: http://localhost:" + str(port))
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
