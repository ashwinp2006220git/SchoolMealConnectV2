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
        -- ── Core user accounts ──────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            role          TEXT    NOT NULL CHECK(role IN ('admin','principal','school_staff','merchant','delivery')),
            name          TEXT    NOT NULL,
            phone         TEXT,
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── Normalised: one row per merchant user ────────────────────────────────
        -- Stores merchant-specific metadata separate from the generic users table.
        -- merchant_id references users.id (1-to-1 for role='merchant' accounts).
        CREATE TABLE IF NOT EXISTS merchants (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            business_name TEXT    NOT NULL,
            address       TEXT,
            description   TEXT,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ── Normalised: lookup table for item categories ─────────────────────────
        -- Keeps category names consistent across the app; avoids free-text bugs.
        CREATE TABLE IF NOT EXISTS categories (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name  TEXT UNIQUE NOT NULL,
            icon  TEXT NOT NULL DEFAULT '📦'
        );

        -- ── Inventory: now references categories.id ──────────────────────────────
        CREATE TABLE IF NOT EXISTS inventory (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id    INTEGER NOT NULL REFERENCES users(id),
            item_name      TEXT    NOT NULL,
            category_id    INTEGER NOT NULL REFERENCES categories(id),
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

    # ── Safe migrations for databases that existed before this refactor ─────────
    # Add is_active to users if upgrading from old schema
    try:
        db.execute('ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1')
        db.commit()
    except Exception:
        pass

    # If inventory still has a text 'category' column (old schema), migrate it
    cols = [r[1] for r in db.execute("PRAGMA table_info(inventory)").fetchall()]
    if 'category' in cols and 'category_id' not in cols:
        _migrate_inventory_category(db)

    # ── Seed data (only on first run) ────────────────────────────────────────────
    if db.execute('SELECT COUNT(*) as c FROM users').fetchone()['c'] == 0:
        _seed(db)

    db.close()


def _migrate_inventory_category(db):
    """Migrate free-text category column → FK to categories table."""
    # Collect distinct category names already in use
    existing_cats = [r[0] for r in db.execute(
        "SELECT DISTINCT category FROM inventory WHERE category IS NOT NULL"
    ).fetchall()]
    icon_map = {'Vegetables': '🥬', 'Grains': '🌾', 'Spices': '🌶️', 'Oils': '🫙', 'Other': '📦'}
    for name in existing_cats:
        db.execute(
            "INSERT OR IGNORE INTO categories (name, icon) VALUES (?, ?)",
            (name, icon_map.get(name, '📦'))
        )
    db.commit()
    # Rename old table and recreate with FK
    db.executescript('''
        ALTER TABLE inventory RENAME TO inventory_old;
        CREATE TABLE inventory (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id    INTEGER NOT NULL REFERENCES users(id),
            item_name      TEXT    NOT NULL,
            category_id    INTEGER NOT NULL REFERENCES categories(id),
            unit           TEXT    NOT NULL,
            quantity       REAL    NOT NULL DEFAULT 0,
            price_per_unit REAL    NOT NULL,
            updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    # Copy rows across
    rows = db.execute("SELECT * FROM inventory_old").fetchall()
    for r in rows:
        cat_id = db.execute(
            "SELECT id FROM categories WHERE name=?", (r['category'],)
        ).fetchone()
        if cat_id:
            db.execute(
                '''INSERT INTO inventory
                   (id, merchant_id, item_name, category_id, unit, quantity, price_per_unit, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (r['id'], r['merchant_id'], r['item_name'],
                 cat_id['id'], r['unit'], r['quantity'],
                 r['price_per_unit'], r['updated_at'])
            )
    db.execute("DROP TABLE inventory_old")
    db.commit()


def _seed(db):
    def h(p): return hashlib.sha256(p.encode()).hexdigest()

    # ── Default categories ───────────────────────────────────────────────────────
    default_categories = [
        ('Vegetables', '🥬'),
        ('Grains',     '🌾'),
        ('Spices',     '🌶️'),
        ('Oils',       '🫙'),
        ('Other',      '📦'),
    ]
    for name, icon in default_categories:
        db.execute("INSERT OR IGNORE INTO categories (name, icon) VALUES (?, ?)", (name, icon))
    db.commit()

    def cat_id(name):
        return db.execute("SELECT id FROM categories WHERE name=?", (name,)).fetchone()['id']

    # ── Users ────────────────────────────────────────────────────────────────────
    users = [
        ('admin',      h('admin123'),  'admin',        'System Administrator',   '9000000000'),
        ('principal',  h('demo123'),   'principal',    'Mrs. Lakshmi Devi',      '9876543210'),
        ('staff1',     h('demo123'),   'school_staff', 'Mr. Rajan Kumar',        '9876543211'),
        ('merchant1',  h('demo123'),   'merchant',     'Annamalai Vegetables',   '9876543212'),
        ('merchant2',  h('demo123'),   'merchant',     'Sri Ganesh Provisions',  '9876543213'),
        ('delivery1',  h('demo123'),   'delivery',     'Murugan Delivery Co.',   '9876543214'),
    ]
    for row in users:
        db.execute('INSERT INTO users (username,password_hash,role,name,phone) VALUES (?,?,?,?,?)', row)
    db.commit()

    m1_uid = db.execute("SELECT id FROM users WHERE username='merchant1'").fetchone()['id']
    m2_uid = db.execute("SELECT id FROM users WHERE username='merchant2'").fetchone()['id']

    # ── Merchant profiles ────────────────────────────────────────────────────────
    db.execute(
        "INSERT INTO merchants (user_id, business_name, description) VALUES (?,?,?)",
        (m1_uid, 'Annamalai Vegetables', 'Fresh daily vegetables supplier for government schools')
    )
    db.execute(
        "INSERT INTO merchants (user_id, business_name, description) VALUES (?,?,?)",
        (m2_uid, 'Sri Ganesh Provisions', 'Grains, spices and cooking essentials wholesaler')
    )
    db.commit()

    # ── Inventory ────────────────────────────────────────────────────────────────
    items_m1 = [
        (m1_uid, 'Tomatoes',  'Vegetables', 'kg',  50, 28.0),
        (m1_uid, 'Onions',    'Vegetables', 'kg',  80, 22.0),
        (m1_uid, 'Potatoes',  'Vegetables', 'kg',  60, 18.0),
        (m1_uid, 'Spinach',   'Vegetables', 'kg',  20, 15.0),
        (m1_uid, 'Carrots',   'Vegetables', 'kg',  30, 25.0),
        (m1_uid, 'Brinjal',   'Vegetables', 'kg',  25, 20.0),
    ]
    items_m2 = [
        (m2_uid, 'Rice (Ponni)',      'Grains', 'kg', 200, 42.0),
        (m2_uid, 'Toor Dal',          'Grains', 'kg', 100, 110.0),
        (m2_uid, 'Cooking Oil',       'Oils',   'L',   50, 135.0),
        (m2_uid, 'Salt',              'Spices', 'kg',  30, 18.0),
        (m2_uid, 'Turmeric Powder',   'Spices', 'g',  500, 2.0),
        (m2_uid, 'Red Chili Powder',  'Spices', 'g',  400, 3.5),
        (m2_uid, 'Mustard Seeds',     'Spices', 'g',  600, 1.2),
        (m2_uid, 'Cumin Seeds',       'Spices', 'g',  300, 4.0),
    ]
    for it in items_m1 + items_m2:
        uid, name, cat_name, unit, qty, price = it
        db.execute(
            '''INSERT INTO inventory
               (merchant_id, item_name, category_id, unit, quantity, price_per_unit)
               VALUES (?,?,?,?,?,?)''',
            (uid, name, cat_id(cat_name), unit, qty, price)
        )
    db.commit()
