"""Turns game data into Telegram messages (text + inline keyboards)."""
from __future__ import annotations

import json
from dataclasses import dataclass

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import config as C
from . import core, engine as E, events, fmt, progress, social, trading
from .core import display_name, price
from .fmt import esc
from .texts import level_title, t


@dataclass
class Reply:
    text: str | None = None
    kb: InlineKeyboardMarkup | None = None
    photo: bytes | str | None = None
    toast: str | None = None
    alert: bool = False
    edit: bool = False


def kb(rows: list) -> InlineKeyboardMarkup | None:
    """rows of (label, callback_data) or (label, url, "url")."""
    out = []
    for row in rows:
        btns = []
        for b in row:
            if len(b) == 3:
                btns.append(InlineKeyboardButton(text=b[0], url=b[1]))
            else:
                btns.append(InlineKeyboardButton(text=b[0], callback_data=b[1]))
        if btns:
            out.append(btns)
    return InlineKeyboardMarkup(inline_keyboard=out) if out else None


KIND_EMOJI = {"personal": "👤", "meme": "🤪", "project": "🎯", "bluechip": "💎", "company": "🏢", "index": "👥"}


# --- stock card ---------------------------------------------------------------------
def stock_card(db, lang: str, s, uid: int | None = None) -> Reply:
    s = core.stock_row(db, s["id"])
    L = lang
    lines = [f"{KIND_EMOJI.get(s['kind'], '📈')} <b>{esc(s['name'])}</b> {fmt.tk(s['ticker'])}"]
    if s["status"] != "active":
        lines.append(t(L, "e.delisted", ticker=fmt.tk(s["ticker"])))
        return Reply(text="\n".join(lines))
    if s["descr"]:
        lines.append(f"<i>{esc(s['descr'])}</i>")
    lines.append(t(L, "card.price", price=fmt.price(price(s), L), chg=fmt.pct(core.change_pct(db, s), L)))
    lines.append(t(L, "card.stats", mcap=fmt.coins(core.mcap(s), L), supply=fmt.num(s["supply"], L), holders=fmt.num(s["holders"], L)))
    if s["kind"] in C.OWNER_KINDS and s["owner_id"]:
        o = core.get_user(db, s["owner_id"])
        if o:
            lines.append(t(L, "card.owner", owner=esc(display_name(o)), rep=fmt.num(o["rep"], L)))
        if s["div_pct"]:
            lines.append(t(L, "card.div", pct=fmt.num(s["div_pct"], L)))
    elif s["kind"] == "company":
        c = db.q1("SELECT owner_id FROM companies WHERE id=?", (s["company_id"],))
        o = core.get_user(db, c["owner_id"]) if c else None
        lines.append(t(L, "card.company", owner=esc(display_name(o)) if o else "-"))
    elif s["kind"] == "index":
        lines.append(t(L, "card.index"))
    if s["goal"]:
        if s["funded"]:
            lines.append(t(L, "card.funded"))
        else:
            frac = s["reserve"] / s["goal"]
            lines.append(t(L, "card.goal", bar=fmt.bar(frac), pct=fmt.num(int(frac * 100), L)))
    if s["event_until"] > core.now():
        lines.append(t(L, "card.event", kind=t(L, "ev." + s["event_kind"]) if s["event_kind"] else "", left=fmt.dur(s["event_until"] - core.now(), L)))
    if s["hype"] >= 1:
        lines.append(t(L, "card.hype", n=fmt.num(round(s["hype"]), L)))
    if s["rugs"]:
        lines.append(t(L, "card.rugs", n=fmt.num(s["rugs"], L)))
    if uid:
        h = db.q1("SELECT shares FROM holdings WHERE user_id=? AND stock_id=?", (uid, s["id"]))
        if h:
            lines.append(t(L, "card.mine", shares=fmt.num(h["shares"], L), value=fmt.coins(core.liq(s, h["shares"]), L)))
    sid = s["id"]
    rows = [
        [(t(L, "btn.buy", n=fmt.num(n, L)), f"b:{sid}:{n}") for n in (1, 10, 100)],
        [(t(L, "btn.sell", n=fmt.num(10, L)), f"s:{sid}:10"), (t(L, "btn.sellall"), f"s:{sid}:0"), (t(L, "btn.buymax"), f"b:{sid}:0")],
        [(t(L, "btn.refresh"), f"st:{sid}"), (t(L, "btn.chart"), f"ch:{sid}:24h")],
    ]
    return Reply(text="\n".join(lines), kb=kb(rows))


# --- market ---------------------------------------------------------------------------
def market_view(db, lang: str, view: str = "top") -> Reply:
    L = lang
    view = view if view in ("top", "trend", "gain", "lose", "new") else "top"
    rows = trading.market(db, view, 8)
    tabs = [[(t(L, f"btn.{v}"), f"mk:{v}") for v in ("top", "trend", "gain", "lose", "new")]]
    if not rows:
        return Reply(text=t(L, "market.empty"), kb=kb(tabs))
    lines = [f"<b>{t(L, 'market.' + view)}</b>", ""]
    for i, s in enumerate(rows, 1):
        lines.append(f"{fmt.num(i, L)}. {KIND_EMOJI.get(s['kind'], '')} {fmt.tk(s['ticker'])} {esc(s['name'])} — {fmt.price(price(s), L)} {fmt.pct(core.change_pct(db, s), L)}")
    btns = [(f"${s['ticker']}", f"st:{s['id']}") for s in rows]
    grid = [btns[i:i + 4] for i in range(0, len(btns), 4)]
    return Reply(text="\n".join(lines), kb=kb(tabs + grid))


# --- portfolio / profile ------------------------------------------------------------------
def portfolio_view(db, lang: str, uid: int) -> Reply:
    L = lang
    p = trading.portfolio(db, uid)
    u = p["user"]
    lines = [t(L, "port.head", name=esc(display_name(u))), t(L, "port.cash", cash=fmt.coins(u["cash"], L), nw=fmt.coins(p["networth"], L))]
    if u["pending_div"] or u["pending_inc"]:
        lines.append(t(L, "port.pending", div=fmt.coins(u["pending_div"], L), inc=fmt.coins(u["pending_inc"], L)))
    lines.append("")
    if not p["rows"]:
        lines.append(t(L, "port.empty"))
    for r in p["rows"]:
        lines.append(t(L, "port.row", tk=fmt.tk(r["stock"]["ticker"]), shares=fmt.num(r["shares"], L), value=fmt.coins(r["value"], L), pnl=fmt.pct(r["pct"], L)))
    if p["shorts"]:
        lines += ["", t(L, "shorts_head")]
        for x in p["shorts"]:
            lines.append(f"{fmt.tk(x['stock']['ticker'])} × {fmt.num(x['short']['shares'], L)} @ {fmt.price(x['short']['entry'], L)} → {fmt.pnl(x['pnl'], L)}")
    rows = [[(t(L, "btn.claim") + " " + ("سود" if L == "fa" else "dividends"), f"cl:div:{uid}"), (t(L, "btn.claim") + " " + ("درآمد" if L == "fa" else "income"), f"cl:inc:{uid}")],
            [(t(L, "btn.refresh"), f"pf:{uid}")]]
    return Reply(text="\n".join(lines), kb=kb(rows))


def profile_view(db, lang: str, uid: int) -> Reply:
    L = lang
    info = progress.level_info(db, uid)
    u = info["user"]
    stocks = ", ".join(fmt.tk(s["ticker"]) for s in trading.my_stocks(db, uid)) or t(L, "none")
    company = t(L, "none")
    if u["company_id"]:
        c = db.q1("SELECT name FROM companies WHERE id=?", (u["company_id"],))
        company = esc(c["name"]) if c else t(L, "none")
    text = t(L, "profile", name=esc(display_name(u)), level=fmt.num(info["level"], L), title=level_title(L, info["level"]), cash=fmt.coins(u["cash"], L),
             nw=fmt.coins(info["nw"], L), rep=fmt.num(u["rep"], L), rb=fmt.num(u["rebirths"], L), streak=fmt.num(u["streak"], L), company=company, stocks=stocks)
    return Reply(text=text)


def level_view(db, lang: str, uid: int) -> Reply:
    L = lang
    i = progress.level_info(db, uid)
    return Reply(text=t(L, "level", level=fmt.num(i["level"], L), title=level_title(L, i["level"]), bar=fmt.bar(i["frac"]), pct=fmt.pct(i["frac"] * 100, L, arrows=False),
                        nw=fmt.coins(i["nw"], L), next=fmt.coins(i["next"], L), free=fmt.num(i["points_free"], L), total=fmt.num(i["points_total"], L)))


def rep_view(db, lang: str, uid: int) -> Reply:
    r = progress.reputation_info(db, uid)
    return Reply(text=t(lang, "rep", rep=fmt.num(r["rep"], lang), mult=fmt.num(r["launch_mult"], lang), rugs=fmt.num(r["rugs"], lang)))


# --- perks ---------------------------------------------------------------------------------
def perks_view(db, lang: str, uid: int, kind: str) -> Reply:
    L = lang
    u = core.need_user(db, uid)
    items = progress.perk_list(db, uid, kind)
    if kind == "skill":
        head = t(L, "skills.head", free=fmt.num(progress.points_free(u), L))
    else:
        head = t(L, "legacy.head", pts=fmt.num(u["legacy_pts"], L), total=fmt.num(u["legacy_total"], L))
    lines = [head, ""]
    btns = []
    for it in items:
        name = t(L, f"perk.{it['key']}.name")
        cost = t(L, "perk.maxed") if it["cost"] is None else t(L, "perk.cost", cost=fmt.num(it["cost"], L))
        lines.append(t(L, "perk.row", name=name, lvl=fmt.num(it["level"], L), max=fmt.num(it["max"], L), cost=cost, desc=t(L, f"perk.{it['key']}.desc")))
        if it["cost"] is not None:
            btns.append((t(L, "perk.btn", name=name, cost=fmt.num(it["cost"], L)), f"up:{it['key']}:{uid}"))
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([("🌳", f"sk:{uid}"), ("🏛", f"lg:{uid}")])
    return Reply(text="\n".join(lines), kb=kb(rows))


def rebirth_view(db, lang: str, uid: int) -> Reply:
    L = lang
    i = progress.rebirth_info(db, uid)
    text = t(L, "rb.info", need=fmt.coins(i["need"], L), nw=fmt.coins(i["nw"], L), gain=fmt.num(i["gain"], L), count=fmt.num(i["count"] + 1, L))
    rows = [[(t(L, "btn.yes"), f"rb:ok:{uid}")] if i["ok"] else [], [(t(L, "btn.cancel"), f"rb:no:{uid}")]]
    return Reply(text=text, kb=kb(rows))


# --- company ---------------------------------------------------------------------------------
def company_view(db, lang: str, uid: int) -> Reply:
    L = lang
    info = social.company_info(db, uid)
    c, members, st = info["company"], info["members"], info["stock"]
    owner = next((m for m in members if m["id"] == c["owner_id"]), None)
    mem_lines = "\n".join(f"• {esc(display_name(m))} — {fmt.coins(m['nw'], L)}" for m in members)
    head = t(L, "company.head", name=esc(c["name"]), tk=fmt.tk(st["ticker"]) if st else "")
    body = t(L, "company.body", owner=esc(display_name(owner)) if owner else "-", n=fmt.num(len(members), L), max=fmt.num(C.COMPANY_MAX_MEMBERS, L),
             members=mem_lines, treasury=fmt.coins(c["treasury"], L), syn=fmt.num(min(20, (len(members) - 1) * C.COMPANY_SYNERGY_PER_MEMBER), L))
    rows = [[(f"${st['ticker']}", f"st:{st['id']}")]] if st else []
    return Reply(text=head + "\n" + body, kb=kb(rows))


# --- news / events / season ---------------------------------------------------------------------
INT_KEYS = {"pct", "minutes", "n", "season"}


def render_news(lang: str, row) -> str:
    kw = {}
    for k, v in json.loads(row["params"] or "{}").items():
        if k == "ticker":
            kw["tk"] = fmt.tk(v)
        elif k in INT_KEYS:
            kw[k] = fmt.num(v, lang)
        else:
            kw[k] = esc(v)
    return t(lang, "news." + row["kind"], **kw)


def news_view(db, lang: str, limit: int = 10) -> Reply:
    rows = db.qa("SELECT * FROM news ORDER BY id DESC LIMIT ?", (limit,))
    if not rows:
        return Reply(text=t(lang, "news.head") + "\n\n" + t(lang, "news.empty"))
    return Reply(text=t(lang, "news.head") + "\n\n" + "\n".join(render_news(lang, r) for r in rows))


def events_view(db, lang: str) -> Reply:
    L = lang
    ev = events.active_events(db)
    lines = [t(L, "ev.head"), ""]
    shown = False
    if ev["fee_free"]:
        lines.append(t(L, "ev.feefree", left=fmt.dur(ev["fee_free"], L)))
        shown = True
    g = ev["global"]
    if g:
        pct = (g["bps"] - C.BPS) / 100
        lines.append(t(L, "ev.global", kind=t(L, "ev." + g["kind"]), pct=fmt.pct(pct, L), left=fmt.dur(g["until"] - core.now(), L)))
        shown = True
    for r in ev["stocks"]:
        pct = (r["event_bps"] - C.BPS) / 100
        lines.append(f"{fmt.tk(r['ticker'])} — {t(L, 'ev.' + r['event_kind']) if r['event_kind'] else ''} {fmt.pct(pct, L)} • {fmt.dur(r['event_until'] - core.now(), L)}")
        shown = True
    if not shown:
        lines.append(t(L, "ev.none"))
    return Reply(text="\n".join(lines))


def season_view(db, lang: str) -> Reply:
    L = lang
    info = progress.season_info(db)
    lines = [t(L, "season.head", id=fmt.num(info["id"], L), left=fmt.dur(info["left"], L))]
    top = progress.season_standings(db, 10)
    if not top:
        lines.append(t(L, "season.empty"))
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(top):
        mark = medals[i] if i < 3 else f"{fmt.num(i + 1, L)}."
        lines.append(f"{mark} {esc(display_name(r))} — {fmt.pnl(r['gain'], L)}")
    p = [f"{fmt.coins(c, L)} + {fmt.num(lp, L)}🏛" for c, lp in C.SEASON_REWARDS]
    lines.append(t(L, "season.prizes", p1=p[0], p2=p[1], p3=p[2]))
    return Reply(text="\n".join(lines))


# --- leaderboards -------------------------------------------------------------------------------
def _rows(lang: str, rows) -> str:
    medals = ["🥇", "🥈", "🥉"]
    out = []
    for i, r in enumerate(rows):
        mark = medals[i] if i < 3 else f"{fmt.num(i + 1, lang)}."
        out.append(t(lang, "lb.row", i=mark, name=esc(display_name(r)), nw=fmt.coins(r["nw"], lang), level=fmt.num(r["max_level"], lang)).replace(f"{mark}. ", f"{mark} ", 1))
    return "\n".join(out)


def leaderboard_view(db, lang: str, chat_id: int) -> Reply:
    rows = social.group_leaderboard(db, chat_id, 10)
    return Reply(text=t(lang, "lb.head") + "\n\n" + (_rows(lang, rows) if rows else t(lang, "season.empty")))


def top_view(db, lang: str) -> Reply:
    rows = social.global_top(db, 10)
    return Reply(text=t(lang, "top.head") + "\n\n" + (_rows(lang, rows) if rows else t(lang, "season.empty")))


def grouprank_view(db, lang: str) -> Reply:
    rows = social.group_ranking(db, 10)
    medals = ["🥇", "🥈", "🥉"]
    lines = [t(lang, "grouprank.head"), ""]
    for i, r in enumerate(rows):
        mark = medals[i] if i < 3 else f"{fmt.num(i + 1, lang)}."
        lines.append(f"{mark} {esc(r['title'])} — {fmt.coins(r['score'], lang)}")
    if not rows:
        lines.append(t(lang, "season.empty"))
    return Reply(text="\n".join(lines))


def group_view(db, lang: str, chat_id: int) -> Reply:
    L = lang
    i = social.group_info(db, chat_id)
    g, idx = i["group"], i["index"]
    text = t(L, "group.info", title=esc(g["title"]), rank=fmt.num(i["rank"], L), members=fmt.num(i["members"], L), score=fmt.coins(g["score"], L),
             tk=fmt.tk(idx["ticker"]) if idx else "", price=fmt.price(price(idx), L) if idx else "")
    if i["top"]:
        text += t(L, "group.top", rows=_rows(L, i["top"]))
    return Reply(text=text, kb=kb([[(f"${idx['ticker']}", f"st:{idx['id']}")]]) if idx else None)


def settings_view(db, lang: str, chat_id: int) -> Reply:
    L = lang
    g = social.get_group(db, chat_id)
    text = t(L, "settings", lang=t(g["lang"], "lang_name"), mode=t(L, "mode." + g["news_mode"]), cap=fmt.num(g["msg_cap"], L))
    return Reply(text=text, kb=kb([[(t(L, "btn.lang"), f"set:lang:{chat_id}"), (t(L, "btn.mode"), f"set:mode:{chat_id}"), (t(L, "btn.cap"), f"set:cap:{chat_id}")]]))


# --- shop / alerts --------------------------------------------------------------------------------
def shop_view(lang: str) -> Reply:
    rows = [[(t(lang, "shop.item", name=t(lang, f"shop.{k}.t"), stars=fmt.num(v["stars"], lang)), f"shop:{k}")] for k, v in C.SHOP_ITEMS.items()]
    return Reply(text=t(lang, "shop.head"), kb=kb(rows))


def alerts_view(db, lang: str, uid: int) -> Reply:
    rows = trading.list_alerts(db, uid)
    if not rows:
        return Reply(text=t(lang, "alerts_empty"))
    lines = [t(lang, "alerts_head")]
    for a in rows:
        lines.append(f"{fmt.tk(a['ticker'])} {t(lang, 'dir.' + a['direction'])} {fmt.price(a['price'], lang)}")
    return Reply(text="\n".join(lines))


# --- group board / direct messages -----------------------------------------------------------------
def board_text(db, lang: str) -> str:
    L = lang
    rows = trading.market(db, "top", 5)
    lines = [t(L, "board.head", brand=t(L, "brand")), ""]
    for s in rows:
        lines.append(f"{KIND_EMOJI.get(s['kind'], '')} {fmt.tk(s['ticker'])} {fmt.price(price(s), L)} {fmt.pct(core.change_pct(db, s), L)}")
    if not rows:
        lines.append(t(L, "market.empty"))
    news = db.qa("SELECT * FROM news ORDER BY id DESC LIMIT 3")
    if news:
        lines += ["", t(L, "board.news")] + [render_news(L, r) for r in news]
    return "\n".join(lines)


def dm_text(lang: str, key: str, kw: dict) -> str:
    out = {}
    for k, v in kw.items():
        if k == "ticker":
            out["tk"] = fmt.tk(v)
        elif k in ("amount", "payout", "coins"):
            out[k] = fmt.coins(v, lang)
        elif k in ("price", "target"):
            out[k] = fmt.price(v, lang)
        elif isinstance(v, int):
            out[k] = fmt.num(v, lang)
        else:
            out[k] = esc(v)
    return t(lang, "n." + key, **out)
