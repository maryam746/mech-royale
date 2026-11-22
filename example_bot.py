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

def decide(o):
    s = o["self"]
    px, py, pz = s["pos"]
    a = {"tick": o["tick"]}
    z = o.get("zone")
    move = [0.0, 0.0]
    boost = False

    # where to go: next zone center
    if z:
        cx, cy = z.get("next_center") or z["center"]
        nr = z.get("next_radius") or z["radius"]
        dx, dy = cx - px, cy - py
        d = math.hypot(dx, dy) or 1.0
        if not s.get("in_zone", True):
            dx, dy = z["center"][0] - px, z["center"][1] - py
            d = math.hypot(dx, dy) or 1.0
            move = [dx / d, dy / d]
            boost = s["energy"] > 20
        elif d > nr * 0.5:
            move = [dx / d, dy / d]
        else:
            move = [-dy / d * 0.4, dx / d * 0.4]  # strafe near center

    # nearby weapon pickups (laser / lightning only)
    have = [w["kind"] for w in s["weapons"] if w]
    best = None
    for p in o.get("pickups", []):
        if p["kind"] in ("laser", "lightning") and p["kind"] not in have:
            d = math.hypot(p["pos"][0] - px, p["pos"][1] - py)
            if d < 40 and (best is None or d < best[0]):
                best = (d, p)
    if best and s.get("in_zone", True) and None in s["weapons"]:
        d, p = best
        if d < 3.5 and abs(p["pos"][2] - pz) < 4:
            a["take"] = p["id"]
        else:
            move = [(p["pos"][0] - px) / d, (p["pos"][1] - py) / d]

    # target: nearest visible mech
    tgt, td = None, 1e9
    for m in o.get("mechs", []):
        if m.get("kind") == "mech":
            d = math.hypot(m["pos"][0] - px, m["pos"][1] - py)
            if d < td:
                tgt, td = m, d
    fire = [False, False]
    if tgt:
        tx, ty, tz = tgt["pos"]
        vx, vy = tgt["vel"][0], tgt["vel"][1]
        t = td / 252.0
        for _ in range(2):
            ex, ey = tx + vx * t, ty + vy * t
            t = math.hypot(ex - px, ey - py) / 252.0
        ex, ey = tx + vx * t, ty + vy * t
        hd = math.hypot(ex - px, ey - py) or 1.0
        yaw = math.atan2(ey - py, ex - px)
        pitch = math.atan2((tz + 4.5) - (pz + 7.0), hd)
        a["aim"] = [yaw, pitch]
        g = s["weapons"][0]
        fire[0] = bool(g and g["ammo"] > 0 and td < 200)
        w1 = s["weapons"][1]
        if w1:
            fire[1] = (w1["kind"] == "lightning" and td < 40) or (w1["kind"] == "laser" and td < 250)
        if g and g["ammo"] == 0:
            a["reload"] = True
    else:
        yaw = None
        for e in o.get("events", []):
            if e.get("type") == "damaged" and e.get("bearing") is not None:
                yaw = e["bearing"]
        if yaw is None and (move[0] or move[1]):
            yaw = math.atan2(move[1], move[0])
        if yaw is not None:
            a["aim"] = [yaw, 0.0]

    a["move"] = move
    a["boost"] = boost
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
        # skip to the newest observation if several queued
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