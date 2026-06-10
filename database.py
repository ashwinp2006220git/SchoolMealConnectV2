import sqlite3, hashlib
from flask import g
import os

DATABASE = os.path.join(os.path.dirname(__file__), 'schoolmeal.db')

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

def init_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            role          TEXT    NOT NULL CHECK(role IN ('principal','school_staff','merchant','delivery')),
            name          TEXT    NOT NULL,
            phone         TEXT,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS inventory (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id    INTEGER NOT NULL REFERENCES users(id),
            item_name      TEXT    NOT NULL,
            category       TEXT    NOT NULL,
            unit           TEXT    NOT NULL,
            quantity       REAL    NOT NULL DEFAULT 0,
            price_per_unit REAL    NOT NULL,
            updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS orders (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            placed_by    INTEGER NOT NULL REFERENCES users(id),
            delivery_id  INTEGER REFERENCES users(id),
            status       TEXT    NOT NULL DEFAULT 'pending'
                             CHECK(status IN ('pending','confirmed','out_for_delivery','delivered','cancelled')),
            total_amount REAL    NOT NULL DEFAULT 0,
            notes        TEXT,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS order_items (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id     INTEGER NOT NULL REFERENCES orders(id),
            inventory_id INTEGER REFERENCES inventory(id),
            item_name    TEXT    NOT NULL,
            quantity     REAL    NOT NULL,
            unit         TEXT    NOT NULL,
            unit_price   REAL    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ai_suggestions (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name         TEXT NOT NULL,
            category          TEXT,
            suggested_qty     REAL NOT NULL,
            unit              TEXT NOT NULL,
            basis_attendance  INTEGER,
            generated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    db.commit()
    # Seed demo accounts if empty
    existing = db.execute('SELECT COUNT(*) as c FROM users').fetchone()['c']
    if existing == 0:
        def h(p): return hashlib.sha256(p.encode()).hexdigest()
        users = [
            ('principal',  h('demo123'), 'principal',    'Mrs. Lakshmi Devi',      '9876543210'),
            ('staff1',     h('demo123'), 'school_staff', 'Mr. Rajan Kumar',        '9876543211'),
            ('merchant1',  h('demo123'), 'merchant',     'Annamalai Vegetables',   '9876543212'),
            ('merchant2',  h('demo123'), 'merchant',     'Sri Ganesh Provisions',  '9876543213'),
            ('delivery1',  h('demo123'), 'delivery',     'Murugan Delivery Co.',   '9876543214'),
        ]
        for row in users:
            db.execute('INSERT INTO users (username,password_hash,role,name,phone) VALUES (?,?,?,?,?)', row)
        db.commit()
        # Seed inventory for merchant1
        m1 = db.execute("SELECT id FROM users WHERE username='merchant1'").fetchone()['id']
        m2 = db.execute("SELECT id FROM users WHERE username='merchant2'").fetchone()['id']
        items_m1 = [
            (m1,'Tomatoes','Vegetables','kg',50,28.0),
            (m1,'Onions','Vegetables','kg',80,22.0),
            (m1,'Potatoes','Vegetables','kg',60,18.0),
            (m1,'Spinach','Vegetables','kg',20,15.0),
            (m1,'Carrots','Vegetables','kg',30,25.0),
            (m1,'Brinjal','Vegetables','kg',25,20.0),
        ]
        items_m2 = [
            (m2,'Rice (Ponni)','Grains','kg',200,42.0),
            (m2,'Toor Dal','Grains','kg',100,110.0),
            (m2,'Cooking Oil','Oils','L',50,135.0),
            (m2,'Salt','Spices','kg',30,18.0),
            (m2,'Turmeric Powder','Spices','g',500,2.0),
            (m2,'Red Chili Powder','Spices','g',400,3.5),
            (m2,'Mustard Seeds','Spices','g',600,1.2),
            (m2,'Cumin Seeds','Spices','g',300,4.0),
        ]
        for it in items_m1 + items_m2:
            db.execute('INSERT INTO inventory (merchant_id,item_name,category,unit,quantity,price_per_unit) VALUES (?,?,?,?,?,?)', it)
        db.commit()
    db.close()
