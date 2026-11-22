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
            # also stay well inside the current circle
            dc = math.hypot(cx - px, cy - py)
            if dc > z["radius"] * 0.85:
                mx, my = norm(cx - px, cy - py)

    # ---------- loot (only when safe) ----------
    take = None
    if near_enemy > 60 and in_zone:
        goal = None
        # supply drop on the ground
        for dr in o.get("drops", []):
            if dr.get("lands_in", 99) <= 1.0 and dr.get("holder") in (None, s["id"]):
                dd = math.hypot(dr["pos"][0] - px, dr["pos"][1] - py)
                if dd < 160 and (goal is None or dd < goal[0]):
                    goal = (dd, dr["pos"])
        # weapons
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
        # cubes
        for c in o.get("cubes", []):
            dd = math.hypot(c["pos"][0] - px, c["pos"][1] - py)
            if dd < 25 and (goal is None or dd < goal[0]):
                goal = (dd, c["pos"])
        if goal:
            mx, my = norm(goal[1][0] - px, goal[1][1] - py)
    if take is not None:
        a["take"] = take

    # ---------- combat ----------
    fire = [False, False]
    if enemies:
        d, t = enemies[0]
        tx, ty, tz = t["pos"]
        tvx, tvy = t["vel"][0], t["vel"][1]
        gs = 252.0
        if g and g.get("stats"):
            gs = g["stats"].get("speed", 252.0)
        tt = d / gs
        for _ in range(2):
            ex, ey = tx + tvx * tt, ty + tvy * tt
            tt = math.hypot(ex - px, ey - py) / gs
        ex, ey = tx + tvx * tt, ty + tvy * tt
        hd = math.hypot(ex - px, ey - py) or 1.0
        yaw = math.atan2(ey - py, ex - px)
        pitch = math.atan2((tz + 4.5) - (pz + 7.0), hd)
        a["aim"] = [yaw, pitch]

        if g and g["ammo"] > 0 and d < 210:
            fire[0] = True
        if g and g["ammo"] == 0 and g.get("reload", 0) == 0:
            a["reload"] = True

        if w1:
            k = w1["kind"]
            if k == "lightning":
                fire[1] = d < 42 and s["energy"] > 5
            elif k == "laser":
                if d < 260:
                    ch = w1.get("charge", 0) or 0
                    cd = w1.get("cooldown", 0) or 0
                    if ch >= 0.7:
                        fire[1] = False  # release -> fires
                    elif cd <= 0.05 or ch > 0:
                        fire[1] = True
            elif k == "mortar":
                if 25 < d < 220:
                    R = hd
                    tf = R / (72.0 * 0.8)
                    ex2, ey2 = tx + tvx * tf, ty + tvy * tf
                    R2 = math.hypot(ex2 - px, ey2 - py)
                    a["aim"] = [math.atan2(ey2 - py, ex2 - px), mortar_pitch(R2)]
                    fire[1] = True
                    fire[0] = False  # keep aim on the shell arc
        # ---------- movement: strafe / back off ----------
        if tick >= ST["next_flip"]:
            ST["sign"] = -ST["sign"]
            ST["next_flip"] = tick + 10 + (tick * 7919) % 8
        ux, uy = norm(tx - px, ty - py)
        perp = (-uy * ST["sign"], ux * ST["sign"])
        if d < 35:
            cmx, cmy = -ux * 0.7 + perp[0] * 0.8, -uy * 0.7 + perp[1] * 0.8
        elif d < 110:
            cmx, cmy = perp[0] * 0.9 + mx * 0.3, perp[1] * 0.9 + my * 0.3
        else:
            cmx, cmy = mx * 0.7 + perp[0] * 0.4, my * 0.7 + perp[1] * 0.4
        # never wander out of the zone while fighting
        if z and in_zone:
            dc = math.hypot(z["center"][0] - px, z["center"][1] - py)
            if dc > z["radius"] * 0.9:
                zx, zy = norm(z["center"][0] - px, z["center"][1] - py)
                cmx, cmy = cmx * 0.3 + zx, cmy * 0.3 + zy
        mx, my = norm(cmx, cmy)
    else:
        yaw = None
        for e in o.get("events", []):
            if e.get("type") == "damaged" and e.get("bearing") is not None:
                yaw = e["bearing"]
        if yaw is None and (mx or my):
            yaw = math.atan2(my, mx)
        if yaw is not None:
            a["aim"] = [yaw, 0.0]

    # ---------- stuck detection ----------
    jump = False
    if (mx or my) and math.hypot(vx, vy) < 1.5 and s.get("grounded", True):
        ST["stuck"] += 1
    else:
        ST["stuck"] = 0
    if ST["stuck"] >= 4:
        jump = True
        if s["energy"] > 30:
            boost = True
        if ST["stuck"] >= 8:
            mx, my = -my, mx  # try a sideways direction
            ST["stuck"] = 0
    elif not s.get("grounded", True) and ST["stuck"] == 0:
        pass

    a["move"] = [mx, my]
    a["boost"] = boost
    a["jump"] = jump
    a["fire"] = fire

    off = o.get("offer")
    if off:
        idx = 0
        for i, c in enumerate(off["choices"]):
            if c["id"] == "armor":
                idx = i
        a["pick"] = idx
    return a

def main():
    first = q.get()
    if first is None:
        return
    send({"type": "ready", "name": "last-mech-standing"})
    while True:
        line = q.get()
        if line is None:
            return
        try:
            m = json.loads(line)
        except ValueError:
            continue
        while not q.empty():
            nxt = q.get_nowait()
            if nxt is None:
                return
            try:
                n = json.loads(nxt)
            except ValueError:
                continue
            if n.get("type") == "end":
                return
            if n.get("type") == "obs":
                m = n
        t = m.get("type")
        if t == "end":
            return
        if t != "obs":
            continue
        try:
            send(decide(m))
        except Exception as e:
            sys.stderr.write(f"err {e!r}\n")
            send({"tick": m["tick"]})

main()