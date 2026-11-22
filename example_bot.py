import sys, json, math, threading, queue

q = queue.Queue()

def reader():
    for line in sys.stdin:
        q.put(line)
    q.put(None)

threading.Thread(target=reader, daemon=True).start()

def send(m):
    sys.stdout.write(json.dumps(m, separators=(",", ":")) + "\n")
    sys.stdout.flush()

ST = {"sign": 1, "next_flip": 0, "stuck": 0}

def norm(x, y):
    d = math.hypot(x, y)
    return (x / d, y / d) if d > 1e-6 else (0.0, 0.0)

def mortar_pitch(R):
    k = min(1.0, 22.0 * R / (72.0 * 72.0))
    return 0.5 * math.asin(k)

def decide(o):
    s = o["self"]
    px, py, pz = s["pos"]
    vx, vy = s["vel"][0], s["vel"][1]
    tick = o["tick"]
    a = {"tick": tick}
    ws = s["weapons"]
    g = ws[0] if len(ws) > 0 else None
    w1 = ws[1] if len(ws) > 1 else None
    z = o.get("zone")
    in_zone = s.get("in_zone", True)

    enemies = []
    for m in o.get("mechs", []):
        if m.get("kind") == "mech":
            d = math.hypot(m["pos"][0] - px, m["pos"][1] - py)
            enemies.append((d, m))
    enemies.sort(key=lambda e: e[0])
    near_enemy = enemies[0][0] if enemies else 1e9

    # ---------- goal: zone ----------
    mx, my = 0.0, 0.0
    boost = False
    if z:
        cx, cy = z["center"]
        ncx, ncy = z.get("next_center") or z["center"]
        nr = z.get("next_radius") or z["radius"]
        if not in_zone:
            mx, my = norm(cx - px, cy - py)
            boost = s["energy"] > 15
        else:
            d = math.hypot(ncx - px, ncy - py)
            if d > nr * 0.6:
                mx, my = norm(ncx - px, ncy - py)
            dc = math.hypot(cx - px, cy - py)
            if dc > z["radius"] * 0.85:
                mx, my = norm(cx - px, cy - py)

    # ---------- loot (only when safe) ----------
    take = None
    if near_enemy > 60 and in_zone:
        goal = None
        for dr in o.get("drops", []):
            if dr.get("lands_in", 99) <= 1.0 and dr.get("holder") in (None, s["id"]):
                dd = math.hypot(dr["pos"][0] - px, dr["pos"][1] - py)
                if dd < 160 and (goal is None or dd < goal[0]):
                    goal = (dd, dr["pos"])
        have = [w["kind"] for w in ws if w]
        free = (w1 is None) or (g is None)
        if free:
            for p in o.get("pickups", []):
                if p["kind"] in have or p["kind"] == "gun":
                    continue
                dd = math.hypot(p["pos"][0] - px, p["pos"][1] - py)
                if dd < 45 and (goal is None or dd < goal[0]):
                    goal = (dd, p["pos"])
                if dd < 3.5 and abs(p["pos"][2] - pz) < 4:
                    take = p["id"]
        for c in o.get("cubes", []):
            dd = math.hypot(c["pos"][0] - px, c["pos"][1] - py)
            if dd < 25 and (goal is None or dd