from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from db import db
from models import User, Parking, Reservation
from werkzeug.security import generate_password_hash, check_password_hash
from search import geocode_address, fetch_parkings   # narzedzia wyszukiwania
from datetime import datetime
import json
import math
import requests
from pyproj import Geod
import threading


GEOD = Geod(ellps="WGS84")

app = Flask(__name__)

# konfiguracja bazy
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///parking.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = "super_tajny_klucz_zmien_mnie"

db.init_app(app)

with app.app_context():
    db.create_all()


@app.context_processor
def inject_user():
    return {"username": session.get("username")}


# liczenie powierzchni

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def _overpass_query(q: str, timeout=25):
    try:
        res = requests.post(OVERPASS_URL, data={"data": q}, timeout=timeout)
        if res.status_code != 200:
            return None
        return res.json()
    except Exception:
        return None


def _parse_levels_from_tags(tags: dict) -> int:
    if not tags:
        return 1
    for key in ("levels", "building:levels"):
        val = tags.get(key)
        if val is None:
            continue
        try:
            lvl = int(str(val).strip())
            if lvl >= 1:
                return lvl
        except Exception:
            continue
    return 1


def _is_closed_ring(coords):
    if not coords or len(coords) < 4:
        return False
    return math.isclose(coords[0][0], coords[-1][0], rel_tol=0, abs_tol=1e-9) and \
           math.isclose(coords[0][1], coords[-1][1], rel_tol=0, abs_tol=1e-9)


def _ring_area_m2(coords):
    if not coords or len(coords) < 3:
        return 0.0
    if not _is_closed_ring(coords):
        coords = coords + [coords[0]]
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    area, _perim = GEOD.polygon_area_perimeter(lons, lats)  
    return abs(area)


def _coords_from_way(way_obj):
    geom = way_obj.get("geometry")
    if not isinstance(geom, list):
        return None
    out = []
    for pt in geom:
        if "lat" in pt and "lon" in pt:
            out.append((pt["lat"], pt["lon"]))
    return out if len(out) >= 3 else None


def _calc_area_from_way(way_obj) -> float:
    coords = _coords_from_way(way_obj)
    if not coords:
        return 0.0
    return _ring_area_m2(coords)


def _calc_area_from_relation(rel_obj) -> float:
    members = rel_obj.get("members", [])
    if not members:
        return 0.0

    outers = []
    inners = []

    for m in members:
        role = m.get("role")
        geom = m.get("geometry")
        if not geom or not isinstance(geom, list):
            continue
        coords = []
        for pt in geom:
            if "lat" in pt and "lon" in pt:
                coords.append((pt["lat"], pt["lon"]))
        if len(coords) < 3:
            continue
        if not _is_closed_ring(coords):
            coords = coords + [coords[0]]
        if role == "outer":
            outers.append(coords)
        elif role == "inner":
            inners.append(coords)

    if not outers:
        return 0.0

    area_out = sum(_ring_area_m2(r) for r in outers)
    area_in = sum(_ring_area_m2(r) for r in inners) if inners else 0.0
    area = max(area_out - area_in, 0.0)
    return area


def fetch_osm_area_m2(osm_id: str):
    q_way = f"""
    [out:json][timeout:25];
    way({osm_id});
    out tags geom;
    """
    j = _overpass_query(q_way)
    if j and j.get("elements"):
        w = j["elements"][0]
        tags = w.get("tags", {}) or {}
        levels = _parse_levels_from_tags(tags)
        area = _calc_area_from_way(w)
        if area and area > 0:
            return area, levels

    q_rel = f"""
    [out:json][timeout:25];
    relation({osm_id});
    out tags geom;
    """
    j2 = _overpass_query(q_rel)
    if j2 and j2.get("elements"):
        r = j2["elements"][0]
        tags = r.get("tags", {}) or {}
        levels = _parse_levels_from_tags(tags)
        area = _calc_area_from_relation(r)
        if area and area > 0:
            return area, levels

    return None, 1


_inflight_lock = threading.Lock()
_inflight_osm_ids = set()  


def _compute_area_async(osm_id: str):
    try:
        with app.app_context():
            p = Parking.query.filter_by(osm_id=osm_id).first()
            if not p or p.area_m2 is not None:
                return
            area, levels = fetch_osm_area_m2(osm_id)
            if area and area > 0:
                lv = max(int(levels), 1)
                p.area_m2 = float(area) * lv
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
    finally:
        with _inflight_lock:
            _inflight_osm_ids.discard(osm_id)


def ensure_area_computation(osm_id: str):
    with _inflight_lock:
        if osm_id in _inflight_osm_ids:
            return
        _inflight_osm_ids.add(osm_id)
    t = threading.Thread(target=_compute_area_async, args=(osm_id,), daemon=True)
    t.start()


# strony

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        next_url = request.args.get("next") or request.form.get("next")

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session["user_id"] = user.id
            session["username"] = user.username
            return redirect(next_url or url_for("home"))
        else:
            flash("Nieprawidlowy login lub haslo")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if password != confirm:
            flash("Hasla sie nie zgadzaja")
            return redirect(url_for("register"))
        if not username or not email or not password:
            flash("Uzupelnij wszystkie pola")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)
        new_user = User(username=username, email=email, password=hashed_password)
        db.session.add(new_user)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Uzytkownik o takim loginie lub e-mailu juz istnieje.")
            return redirect(url_for("register"))
        flash("Rejestracja udana. Zaloguj sie.")
        return redirect(url_for("login"))

    return render_template("register.html")


# wyszukiwarka chroniona logowaniem
@app.route("/search", endpoint="search")
def search_view():
    if "user_id" not in session:
        flash("Zaloguj sie, aby wyszukac trase.")
        return redirect(url_for("login", next=request.full_path))

    query = request.args.get("query", "").strip()
    if not query:
        flash("Podaj adres do wyszukania.")
        return redirect(url_for("home"))

    coords = geocode_address(query)
    if not coords:
        flash("Nie znaleziono adresu w Krakowie.")
        return redirect(url_for("home"))

    lat, lon = coords
    return render_template("search_results.html", query=query, lat=lat, lon=lon)


# api

@app.route("/api/parkings")
def api_parkings():
    if "user_id" not in session:
        return jsonify({"error": "auth_required"}), 401

    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))
        radius = int(request.args.get("radius", 100))
    except (TypeError, ValueError):
        return jsonify({"error": "bad_params"}), 400

    items = fetch_parkings(lat, lon, radius)

    only_public = request.args.get("only_public")
    if only_public:
        items = [it for it in items if it.get("access_class") == "public"]

    out = []
    for it in items:
        osm_id = str(it["id"])
        p = Parking.query.filter_by(osm_id=osm_id).first()
        if not p:
            area_m2 = None
            try:
                cap = int(it.get("capacity"))
                area_m2 = cap * 16.25
            except (TypeError, ValueError):
                pass

            p = Parking(
                osm_id=osm_id,
                name=it.get("name"),
                lat=it["lat"],
                lon=it["lon"],
                area_m2=area_m2,
            )
            db.session.add(p)
            db.session.commit()

        out_item = dict(it)

        occupied = p.occupied_m2()
        out_item["occupied_m2"] = occupied
        out_item["area_m2"] = p.area_m2
        out_item["free_m2"] = p.free_m2()

        # procent zajetosci
        if p.area_m2 and p.area_m2 > 0:
            percent = round(100 * occupied / p.area_m2)
            if percent < 0:
                percent = 0
            if percent > 100:
                percent = 100
        else:
            percent = 0
        out_item["percent_occupied"] = percent

        out.append(out_item)

    return jsonify({
        "items": out,
        "center": {"lat": lat, "lon": lon},
        "radius": radius
    })


# rezerwacja miejsca
@app.route("/api/parkings/<osm_id>/reserve", methods=["POST"])
def api_reserve(osm_id):
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "auth_required"}), 401

    user_id = session["user_id"]

    active = Reservation.query.filter_by(user_id=user_id, ended_at=None).first()
    if active:
        return jsonify({"ok": False, "error": "already_reserved"}), 400

    p = Parking.query.filter_by(osm_id=str(osm_id)).first()
    if not p:
        return jsonify({"ok": False, "error": "parking_not_found"}), 404

    if p.area_m2 is not None and p.occupied_m2() + 16.25 > p.area_m2:
        return jsonify({"ok": False, "error": "no_space"}), 409

    r = Reservation(user_id=user_id, parking=p)
    db.session.add(r)
    db.session.commit()

    if p.area_m2 is None:
        ensure_area_computation(p.osm_id)

    return jsonify({
        "ok": True,
        "reservation_id": r.id,
        "osm_id": p.osm_id,
        "started_at": r.started_at.isoformat()
    })


# zakonczenie rezerwacji
@app.route("/api/reservations/finish", methods=["POST"])
def api_finish_reservation():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "auth_required"}), 401

    user_id = session["user_id"]
    active = Reservation.query.filter_by(user_id=user_id, ended_at=None).first()
    if not active:
        return jsonify({"ok": False, "error": "no_active"}), 400

    active.ended_at = datetime.utcnow()
    db.session.commit()

    return jsonify({"ok": True})


# aktywna rezerwacja
@app.route("/api/me/active_reservation")
def api_active_reservation():
    if "user_id" not in session:
        return jsonify({"active": False}), 401

    user_id = session["user_id"]
    active = Reservation.query.filter_by(user_id=user_id, ended_at=None).first()
    if not active:
        return jsonify({"active": False})

    return jsonify({
        "active": True,
        "osm_id": active.parking.osm_id,
        "started_at": active.started_at.isoformat()
    })


if __name__ == "__main__":
    app.run(debug=True)
