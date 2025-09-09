from db import db

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
from datetime import datetime
from db import db


class Parking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    osm_id = db.Column(db.String(32), unique=True, index=True, nullable=False)
    name = db.Column(db.String(200))
    lat = db.Column(db.Float, nullable=False)
    lon = db.Column(db.Float, nullable=False)
    area_m2 = db.Column(db.Float)  
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    reservations = db.relationship("Reservation", backref="parking", lazy=True)

    
    def occupied_m2(self) -> float:
        active = [r for r in self.reservations if r.ended_at is None]
        return 16.25 * len(active)  # 12.5 * 1.3

    
    def free_m2(self):
        if self.area_m2 is None:
            return None
        return max(self.area_m2 - self.occupied_m2(), 0.0)

# rezerwacja

class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    parking_id = db.Column(db.Integer, db.ForeignKey('parking.id'), nullable=False)

    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    
    @property
    def is_active(self) -> bool:
        return self.ended_at is None
