from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from database import init_db, get_db
from datetime import datetime, date
import json, hashlib, os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'schoolmeal-dev-secret-2024')

@app.before_request
def setup():
    init_db()

@app.after_request
def add_no_cache_headers(response):
    """
    Prevent the browser from caching any authenticated page.
    This stops the back-button from showing stale protected content
    after the user has logged out (or before they have logged in).
    """
    if current_user():
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def current_user():
    return session.get('user')

def require_role(*roles):
    user = current_user()
    if not user or user['role'] not in roles:
        return redirect(url_for('index'))
    return None

# ── helpers ────────────────────────────────────────────────────────────────────

def get_categories(db):
    """Return all categories as a list of dicts."""
    return [dict(r) for r in db.execute('SELECT * FROM categories ORDER BY name').fetchall()]

# ─── Auth ──────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    if current_user():
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username'].strip()
    password = request.form['password']
    db = get_db()
    user = db.execute(
        'SELECT * FROM users WHERE username=? AND password_hash=? AND is_active=1',
        (username, hash_password(password))
    ).fetchone()
    if user:
        session['user'] = dict(user)
        return redirect(url_for('dashboard'))
    flash('Invalid username or password, or account is disabled.')
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        if len(password) < 7:
            flash('Password must be at least 7 characters.')
            return redirect(url_for('register'))
        role     = request.form['role']
        name     = request.form['name'].strip()
        phone    = request.form.get('phone', '').strip()
        if not phone.isdigit() or len(phone) != 10:
            flash('Phone number must be exactly 10 digits.')
            return redirect(url_for('register'))
        # school_staff and admin accounts cannot be self-registered
        if role in ('admin', 'school_staff'):
            flash('That account type cannot be created via self-registration.')
            return redirect(url_for('register'))
        db = get_db()
        if db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone():
            flash('Username already taken.')
            return redirect(url_for('register'))
        user_id = db.execute(
            'INSERT INTO users (username, password_hash, role, name, phone) VALUES (?,?,?,?,?)',
            (username, hash_password(password), role, name, phone)
        ).lastrowid
        # Auto-create merchant profile row for merchant accounts
        if role == 'merchant':
            db.execute(
                'INSERT INTO merchants (user_id, business_name) VALUES (?,?)',
                (user_id, name)
            )
        db.commit()
        flash('Account created! Please log in.')
        return redirect(url_for('index'))
    return render_template('register.html')

# ─── Dashboard router ──────────────────────────────────────────────────────────

@app.route('/dashboard')
def dashboard():
    user = current_user()
    if not user:
        return redirect(url_for('index'))
    db = get_db()
    role = user['role']
    if role == 'admin':
        return _admin_dashboard(db, user)
    elif role == 'principal':
        return _principal_dashboard(db, user)
    elif role == 'school_staff':
        return _staff_dashboard(db, user)
    elif role == 'merchant':
        return _merchant_dashboard(db, user)
    elif role == 'delivery':
        return _delivery_dashboard(db, user)
    return redirect(url_for('index'))

# ─── Admin dashboard ───────────────────────────────────────────────────────────

def _admin_dashboard(db, user):
    users = db.execute('SELECT * FROM users ORDER BY role, name').fetchall()
    orders = db.execute('''
        SELECT o.*, u.name AS staff_name FROM orders o
        JOIN users u ON o.placed_by = u.id
        ORDER BY o.created_at DESC
    ''').fetchall()
    inventory = db.execute('''
        SELECT i.*, c.name AS category, c.icon AS category_icon,
               u.name AS merchant_name
        FROM inventory i
        JOIN categories c ON i.category_id = c.id
        JOIN users u ON i.merchant_id = u.id
        ORDER BY u.name, c.name, i.item_name
    ''').fetchall()
    stats = {
        'total_users':  db.execute('SELECT COUNT(*) as c FROM users').fetchone()['c'],
        'total_orders': db.execute('SELECT COUNT(*) as c FROM orders').fetchone()['c'],
        'total_spend':  db.execute('SELECT COALESCE(SUM(total_amount),0) as t FROM orders').fetchone()['t'],
        'active_items': db.execute('SELECT COUNT(*) as c FROM inventory WHERE quantity>0').fetchone()['c'],
    }
    categories = get_categories(db)
    return render_template('admin_dashboard.html',
        user=user, users=users, orders=orders, inventory=inventory,
        stats=stats, categories=categories)

# ─── Admin: user management ────────────────────────────────────────────────────

@app.route('/admin/user/add', methods=['POST'])
def admin_user_add():
    guard = require_role('admin')
    if guard: return guard
    db = get_db()
    username = request.form['username'].strip()
    role = request.form['role']
    name = request.form['name'].strip()
    phone = request.form.get('phone', '').strip()
    password = request.form['password']

    if len(password) < 7:
        flash('Password must be at least 7 characters.')
        return redirect(url_for('dashboard'))

    if not phone.isdigit() or len(phone) != 10:
        flash('Phone number must be exactly 10 digits.')
        return redirect(url_for('dashboard'))
    if db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone():
        flash('Username already taken.')
        return redirect(url_for('dashboard'))
    user_id = db.execute(
        'INSERT INTO users (username, password_hash, role, name, phone) VALUES (?,?,?,?,?)',
        (username, hash_password(request.form['password']),
         role, name, request.form.get('phone', '').strip())
    ).lastrowid
    if role == 'merchant':
        db.execute(
            'INSERT INTO merchants (user_id, business_name) VALUES (?,?)',
            (user_id, name)
        )
    db.commit()
    flash(f"User '{username}' created.")
    return redirect(url_for('dashboard'))

@app.route('/admin/user/toggle/<int:uid>', methods=['POST'])
def admin_user_toggle(uid):
    guard = require_role('admin')
    if guard: return guard
    user = current_user()
    if uid == user['id']:
        flash("You cannot disable your own account.")
        return redirect(url_for('dashboard'))
    db = get_db()
    current_state = db.execute('SELECT is_active FROM users WHERE id=?', (uid,)).fetchone()['is_active']
    db.execute('UPDATE users SET is_active=? WHERE id=?', (0 if current_state else 1, uid))
    db.commit()
    flash('User account ' + ('disabled.' if current_state else 'enabled.'))
    return redirect(url_for('dashboard'))

@app.route('/admin/user/delete/<int:uid>', methods=['POST'])
def admin_user_delete(uid):
    guard = require_role('admin')
    if guard: return guard
    user = current_user()
    if uid == user['id']:
        flash("You cannot delete your own account.")
        return redirect(url_for('dashboard'))
    db = get_db()
    db.execute('DELETE FROM inventory WHERE merchant_id=?', (uid,))
    db.execute('DELETE FROM merchants WHERE user_id=?', (uid,))
    db.execute('UPDATE orders SET delivery_id=NULL WHERE delivery_id=?', (uid,))
    db.execute('DELETE FROM users WHERE id=?', (uid,))
    db.commit()
    flash('User deleted.')
    return redirect(url_for('dashboard'))

@app.route('/admin/user/reset_password/<int:uid>', methods=['POST'])
def admin_reset_password(uid):
    guard = require_role('admin')
    if guard: return guard
    new_pw = request.form['new_password']
    if len(new_pw) < 4:
        flash('Password must be at least 4 characters.')
        return redirect(url_for('dashboard'))
    db = get_db()
    db.execute('UPDATE users SET password_hash=? WHERE id=?', (hash_password(new_pw), uid))
    db.commit()
    flash('Password reset successfully.')
    return redirect(url_for('dashboard'))

@app.route('/admin/user/edit/<int:uid>', methods=['POST'])
def admin_user_edit(uid):
    """Admin can edit ALL fields of any user: name, username, phone, password, role."""
    guard = require_role('admin')
    if guard: return guard
    actor = current_user()
    db = get_db()

    target = db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if not target:
        flash('User not found.')
        return redirect(url_for('dashboard'))
    # Prevent admin from changing their own role away from admin
    if uid == actor['id'] and request.form.get('role') != 'admin':
        flash('You cannot change your own role.')
        return redirect(url_for('dashboard'))

    new_username = request.form['username'].strip()
    new_name     = request.form['name'].strip()
    new_phone    = request.form.get('phone', '').strip()
    if new_phone and (not new_phone.isdigit() or len(new_phone) != 10):
        flash('Phone number must be exactly 10 digits.')
        return redirect(url_for('dashboard'))
    new_role     = request.form['role']
    new_pw       = request.form.get('password', '').strip()

    # Username uniqueness check (excluding self)
    clash = db.execute(
        'SELECT id FROM users WHERE username=? AND id!=?', (new_username, uid)
    ).fetchone()
    if clash:
        flash('That username is already taken by another user.')
        return redirect(url_for('dashboard'))

    if new_pw:
        if len(new_pw) < 7:
            flash('Password must be at least 4 characters.')
            return redirect(url_for('dashboard'))
        db.execute(
            'UPDATE users SET username=?, name=?, phone=?, role=?, password_hash=? WHERE id=?',
            (new_username, new_name, new_phone, new_role, hash_password(new_pw), uid)
        )
    else:
        db.execute(
            'UPDATE users SET username=?, name=?, phone=?, role=? WHERE id=?',
            (new_username, new_name, new_phone, new_role, uid)
        )

    # If role changed to merchant and no merchants row exists yet, create one
    if new_role == 'merchant':
        exists = db.execute('SELECT id FROM merchants WHERE user_id=?', (uid,)).fetchone()
        if not exists:
            db.execute('INSERT INTO merchants (user_id, business_name) VALUES (?,?)',
                       (uid, new_name))

    db.commit()
    flash(f"User '{new_username}' updated successfully.")
    return redirect(url_for('dashboard'))

# ─── Admin: order management ───────────────────────────────────────────────────

@app.route('/admin/order/delete/<int:order_id>', methods=['POST'])
def admin_order_delete(order_id):
    guard = require_role('admin')
    if guard: return guard
    db = get_db()
    items = db.execute('SELECT * FROM order_items WHERE order_id=?', (order_id,)).fetchall()
    for item in items:
        if item['inventory_id']:
            db.execute('UPDATE inventory SET quantity = quantity + ? WHERE id=?',
                       (item['quantity'], item['inventory_id']))
    db.execute('DELETE FROM order_items WHERE order_id=?', (order_id,))
    db.execute('DELETE FROM orders WHERE id=?', (order_id,))
    db.commit()
    flash(f'Order #{order_id} deleted and stock restored.')
    return redirect(url_for('dashboard'))

@app.route('/admin/order/status/<int:order_id>', methods=['POST'])
def admin_order_status(order_id):
    guard = require_role('admin')
    if guard: return guard
    new_status = request.form['status']
    db = get_db()
    db.execute('UPDATE orders SET status=? WHERE id=?', (new_status, order_id))
    db.commit()
    flash(f'Order #{order_id} status updated.')
    return redirect(url_for('dashboard'))

# ─── Admin: inventory management ──────────────────────────────────────────────

@app.route('/admin/inventory/delete/<int:item_id>', methods=['POST'])
def admin_inventory_delete(item_id):
    guard = require_role('admin')
    if guard: return guard
    db = get_db()
    db.execute('UPDATE order_items SET inventory_id=NULL WHERE inventory_id=?', (item_id,))
    db.execute('DELETE FROM inventory WHERE id=?', (item_id,))
    db.commit()
    flash('Inventory item removed.')
    return redirect(url_for('dashboard'))

# ─── Admin: category management ───────────────────────────────────────────────

@app.route('/admin/category/add', methods=['POST'])
def admin_category_add():
    guard = require_role('admin')
    if guard: return guard
    db = get_db()
    name = request.form['name'].strip()
    icon = request.form.get('icon', '📦').strip() or '📦'
    if not name:
        flash('Category name is required.')
        return redirect(url_for('dashboard'))
    try:
        db.execute('INSERT INTO categories (name, icon) VALUES (?,?)', (name, icon))
        db.commit()
        flash(f"Category '{name}' added.")
    except Exception:
        flash(f"Category '{name}' already exists.")
    return redirect(url_for('dashboard'))

@app.route('/admin/category/delete/<int:cat_id>', methods=['POST'])
def admin_category_delete(cat_id):
    guard = require_role('admin')
    if guard: return guard
    db = get_db()
    in_use = db.execute('SELECT COUNT(*) as c FROM inventory WHERE category_id=?', (cat_id,)).fetchone()['c']
    if in_use:
        flash(f'Cannot delete: {in_use} inventory item(s) still use this category.')
        return redirect(url_for('dashboard'))
    db.execute('DELETE FROM categories WHERE id=?', (cat_id,))
    db.commit()
    flash('Category deleted.')
    return redirect(url_for('dashboard'))

# ─── Principal: staff management ───────────────────────────────────────────────

@app.route('/principal/staff/add', methods=['POST'])
def principal_staff_add():
    """Principal and admin can create school_staff accounts."""
    guard = require_role('principal', 'admin')
    if guard: return guard
    db = get_db()
    username = request.form['username'].strip()
    name     = request.form['name'].strip()
    phone    = request.form.get('phone', '').strip()
    password = request.form['password']

    if not username or not name or not password:
        flash('Name, username and password are all required.')
        return redirect(url_for('dashboard'))
    if len(password) < 7:
        flash('Password must be at least 4 characters.')
        return redirect(url_for('dashboard'))
    if not phone.isdigit() or len(phone) != 10:
        flash('Phone number must be exactly 10 digits.')
        return redirect(url_for('dashboard'))
    if db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone():
        flash('Username already taken.')
        return redirect(url_for('dashboard'))

    db.execute(
        'INSERT INTO users (username, password_hash, role, name, phone) VALUES (?,?,?,?,?)',
        (username, hash_password(password), 'school_staff', name, phone)
    )
    db.commit()
    flash(f"Staff account '{username}' created successfully.")
    return redirect(url_for('dashboard'))

@app.route('/staff/update_details/<int:uid>', methods=['POST'])
def staff_update_details(uid):
    """
    Update username, phone, and optionally password for a school_staff account.
    Name is NOT editable through this route.
    Allowed callers:
      - admin:        any school_staff user
      - principal:    any school_staff user
      - school_staff: only their own account
    """
    actor = current_user()
    if not actor:
        return redirect(url_for('index'))

    db = get_db()
    target = db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if not target or target['role'] != 'school_staff':
        flash('Target user not found or is not school staff.')
        return redirect(url_for('dashboard'))

    # Permission check
    if actor['role'] == 'school_staff' and actor['id'] != uid:
        flash('You can only edit your own account.')
        return redirect(url_for('dashboard'))
    if actor['role'] not in ('admin', 'principal', 'school_staff'):
        flash('Permission denied.')
        return redirect(url_for('dashboard'))

    new_username = request.form['username'].strip()
    new_phone    = request.form.get('phone', '').strip()
    new_pw       = request.form.get('password', '').strip()

    if not new_username:
        flash('Username cannot be empty.')
        return redirect(url_for('dashboard'))

    # Username uniqueness check (excluding this user)
    clash = db.execute(
        'SELECT id FROM users WHERE username=? AND id!=?', (new_username, uid)
    ).fetchone()
    if clash:
        flash('That username is already taken.')
        return redirect(url_for('dashboard'))

    if new_pw:
        if len(new_pw) < 7:
            flash('Password must be at least 4 characters.')
            return redirect(url_for('dashboard'))
        if new_phone and (not new_phone.isdigit() or len(new_phone) != 10):
            flash('Phone number must be exactly 10 digits.')
            return redirect(url_for('dashboard'))
        db.execute(
            'UPDATE users SET username=?, phone=?, password_hash=? WHERE id=?',
            (new_username, new_phone, hash_password(new_pw), uid)
        )
    else:
        db.execute(
            'UPDATE users SET username=?, phone=? WHERE id=?',
            (new_username, new_phone, uid)
        )

    db.commit()

    # If the logged-in user edited their own record, refresh the session
    if actor['id'] == uid:
        updated = db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
        session['user'] = dict(updated)

    flash('Staff details updated successfully.')
    return redirect(url_for('dashboard'))

# ─── Principal: own profile ────────────────────────────────────────────────────

@app.route('/principal/profile/update', methods=['POST'])
def principal_profile_update():
    """
    Principal can view & edit their own profile: name, username, phone,
    and optionally password. Same restrictions as elsewhere in the app:
      - phone must be exactly 10 digits (if provided)
      - password must be at least 7 characters (if changing it)
    """
    guard = require_role('principal')
    if guard: return guard
    user = current_user()
    db = get_db()

    new_name     = request.form['name'].strip()
    new_username = request.form['username'].strip()
    new_phone    = request.form.get('phone', '').strip()
    new_pw       = request.form.get('password', '').strip()

    if not new_name or not new_username:
        flash('Name and username cannot be empty.')
        return redirect(url_for('dashboard'))

    if not new_phone.isdigit() or len(new_phone) != 10:
        flash('Phone number must be exactly 10 digits.')
        return redirect(url_for('dashboard'))

    # Username uniqueness check (excluding self)
    clash = db.execute(
        'SELECT id FROM users WHERE username=? AND id!=?', (new_username, user['id'])
    ).fetchone()
    if clash:
        flash('That username is already taken by another user.')
        return redirect(url_for('dashboard'))

    if new_pw:
        if len(new_pw) < 7:
            flash('Password must be at least 7 characters.')
            return redirect(url_for('dashboard'))
        db.execute(
            'UPDATE users SET name=?, username=?, phone=?, password_hash=? WHERE id=?',
            (new_name, new_username, new_phone, hash_password(new_pw), user['id'])
        )
    else:
        db.execute(
            'UPDATE users SET name=?, username=?, phone=? WHERE id=?',
            (new_name, new_username, new_phone, user['id'])
        )
    db.commit()

    # Refresh the session so the new details show up immediately
    updated = db.execute('SELECT * FROM users WHERE id=?', (user['id'],)).fetchone()
    session['user'] = dict(updated)

    flash('Your profile was updated successfully.')
    return redirect(url_for('dashboard'))

# ─── Principal dashboard ───────────────────────────────────────────────────────

def _principal_dashboard(db, user):
    today = date.today().isoformat()
    orders = db.execute('''
        SELECT o.*, u.name AS staff_name FROM orders o
        JOIN users u ON o.placed_by = u.id
        ORDER BY o.created_at DESC LIMIT 50
    ''').fetchall()
    total_today = db.execute(
        "SELECT COALESCE(SUM(total_amount),0) as t FROM orders WHERE DATE(created_at)=?", (today,)
    ).fetchone()['t']
    pending = db.execute(
        "SELECT COUNT(*) as c FROM orders WHERE status='pending'"
    ).fetchone()['c']
    delivered = db.execute(
        "SELECT COUNT(*) as c FROM orders WHERE status='delivered' AND DATE(created_at)=?", (today,)
    ).fetchone()['c']
    top_merchants = db.execute('''
        SELECT u.name, COUNT(oi.id) as items_supplied
        FROM order_items oi
        JOIN inventory i ON oi.inventory_id = i.id
        JOIN users u ON i.merchant_id = u.id
        GROUP BY u.id ORDER BY items_supplied DESC LIMIT 5
    ''').fetchall()
    recent_spend = db.execute('''
        SELECT DATE(created_at) as day, SUM(total_amount) as total
        FROM orders WHERE created_at >= date('now','-7 days')
        GROUP BY day ORDER BY day
    ''').fetchall()
    # Staff list for staff management section
    staff_list = db.execute(
        "SELECT id, username, name, phone, is_active, created_at FROM users WHERE role='school_staff' ORDER BY name"
    ).fetchall()
    return render_template('principal_dashboard.html',
        user=user, orders=orders, total_today=total_today,
        pending=pending, delivered=delivered,
        top_merchants=top_merchants, recent_spend=recent_spend,
        staff_list=staff_list)

# ─── Staff dashboard ───────────────────────────────────────────────────────────

def _staff_dashboard(db, user):
    items = db.execute('''
        SELECT i.*, c.name AS category, c.icon AS category_icon,
               u.name AS merchant_name, u.phone AS merchant_phone
        FROM inventory i
        JOIN categories c ON i.category_id = c.id
        JOIN users u ON i.merchant_id = u.id
        WHERE i.quantity > 0 AND u.is_active = 1
        ORDER BY c.name, i.item_name
    ''').fetchall()
    my_orders = db.execute(
        'SELECT * FROM orders WHERE placed_by=? ORDER BY created_at DESC LIMIT 20',
        (user['id'],)
    ).fetchall()
    ai_suggestions = db.execute(
        'SELECT * FROM ai_suggestions WHERE DATE(generated_at)=? ORDER BY item_name',
        (date.today().isoformat(),)
    ).fetchall()
    categories = get_categories(db)
    return render_template('staff_dashboard.html',
        user=user, items=items, my_orders=my_orders,
        ai_suggestions=ai_suggestions, categories=categories)

# ─── Merchant dashboard ────────────────────────────────────────────────────────

def _merchant_dashboard(db, user):
    my_items = db.execute('''
        SELECT i.*, c.name AS category, c.icon AS category_icon
        FROM inventory i
        JOIN categories c ON i.category_id = c.id
        WHERE i.merchant_id=?
        ORDER BY c.name, i.item_name
    ''', (user['id'],)).fetchall()
    my_orders = db.execute('''
        SELECT oi.*, o.id as order_id, o.status, o.created_at, u.name as staff_name
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.id
        JOIN inventory i ON oi.inventory_id = i.id
        JOIN users u ON o.placed_by = u.id
        WHERE i.merchant_id=?
        ORDER BY o.created_at DESC LIMIT 30
    ''', (user['id'],)).fetchall()
    categories = get_categories(db)
    return render_template('merchant_dashboard.html',
        user=user, my_items=my_items, my_orders=my_orders, categories=categories)

# ─── Delivery dashboard ────────────────────────────────────────────────────────

def _delivery_dashboard(db, user):
    available = db.execute(
        "SELECT o.*, u.name as staff_name FROM orders o JOIN users u ON o.placed_by=u.id "
        "WHERE o.status='confirmed' AND o.delivery_id IS NULL ORDER BY o.created_at"
    ).fetchall()
    my_jobs = db.execute(
        "SELECT o.*, u.name as staff_name FROM orders o JOIN users u ON o.placed_by=u.id "
        "WHERE o.delivery_id=? ORDER BY o.created_at DESC LIMIT 20",
        (user['id'],)
    ).fetchall()
    return render_template('delivery_dashboard.html',
        user=user, available=available, my_jobs=my_jobs)

# ─── Inventory (Merchant) ──────────────────────────────────────────────────────

@app.route('/inventory/add', methods=['POST'])
def inventory_add():
    guard = require_role('merchant')
    if guard: return guard
    user = current_user()
    db = get_db()
    cat_id = request.form['category_id']
    db.execute(
        'INSERT INTO inventory (merchant_id, item_name, category_id, unit, quantity, price_per_unit) VALUES (?,?,?,?,?,?)',
        (user['id'], request.form['item_name'], cat_id,
         request.form['unit'], float(request.form['quantity']), float(request.form['price']))
    )
    db.commit()
    flash(f"'{request.form['item_name']}' added to your stock.")
    return redirect(url_for('dashboard'))

@app.route('/inventory/update', methods=['POST'])
def inventory_update():
    guard = require_role('merchant')
    if guard: return guard
    user = current_user()
    db = get_db()
    db.execute(
        'UPDATE inventory SET quantity=?, price_per_unit=? WHERE id=? AND merchant_id=?',
        (float(request.form['quantity']), float(request.form['price']),
         request.form['item_id'], user['id'])
    )
    db.commit()
    flash('Stock updated.')
    return redirect(url_for('dashboard'))

@app.route('/inventory/delete/<int:item_id>', methods=['POST'])
def inventory_delete(item_id):
    guard = require_role('merchant')
    if guard: return guard
    user = current_user()
    db = get_db()
    item = db.execute(
        'SELECT id FROM inventory WHERE id=? AND merchant_id=?', (item_id, user['id'])
    ).fetchone()
    if item:
        # Past orders reference this item via inventory_id (FK). order_items
        # already stores its own copy of item_name/qty/unit/price, so it's
        # safe to null the link before deleting the inventory row.
        db.execute('UPDATE order_items SET inventory_id=NULL WHERE inventory_id=?', (item_id,))
        db.execute('DELETE FROM inventory WHERE id=?', (item_id,))
        db.commit()
        flash('Item removed from stock.')
    return redirect(url_for('dashboard'))

# ─── Orders (School Staff) ────────────────────────────────────────────────────


# Statutory PM POSHAN commercial procurement thresholds
PM_POSHAN_MIN_LIMITS = {
    'rice': 5.0,
    'dal': 2.0,
    'lentil': 2.0,
    'tomato': 1.0,
    'onion': 1.0,
    'potato': 2.0,
    'leafy': 0.5,
    'green': 0.5,
    'oil': 1.0,
    'salt': 0.5,
    'turmeric': 50.0,
    'chili': 50.0,
    'chilli': 50.0,
    'mustard': 30.0,
    'cumin': 30.0
}

@app.route('/order/place', methods=['POST'])
def order_place():
    guard = require_role('school_staff')
    if guard: return guard
    user = current_user()
    db   = get_db()
    
    cart = json.loads(request.form.get('cart', '[]'))
    if not cart:
        flash('Your order is empty.')
        return redirect(url_for('dashboard'))

    errors = []
    validated = []
    
    for item in cart:
        inv = db.execute('SELECT * FROM inventory WHERE id=?', (item['id'],)).fetchone()
        if not inv:
            errors.append(f"Item #{item['id']} no longer exists.")
            continue
            
        requested = float(item['qty'])
        available = float(inv['quantity'])
        item_name_lower = inv['item_name'].lower()
        
        # Determine strict PM POSHAN minimum purchase threshold based on item composition
        min_qty = 1.0  # Standard fallback limit
        for ingredient, statutory_min in PM_POSHAN_MIN_LIMITS.items():
            if ingredient in item_name_lower:
                min_qty = statutory_min
                break

        # Verification Pipeline checks
        if requested < min_qty:
            errors.append(
                f"'{inv['item_name']}': PM POSHAN compliance minimum order quantity is "
                f"{min_qty} {inv['unit']}."
            )
        elif requested > available:
            errors.append(
                f"'{inv['item_name']}': you requested {requested} {inv['unit']} "
                f"but only {available} {inv['unit']} is available."
            )
        else:
            validated.append({'inv': inv, 'qty': requested})

    if errors:
        for e in errors:
            flash(e)
        return redirect(url_for('dashboard'))

    # Atomic Database Transaction Execution Block
    total = sum(v['inv']['price_per_unit'] * v['qty'] for v in validated)
    order_id = db.execute(
        'INSERT INTO orders (placed_by, total_amount, notes) VALUES (?,?,?)',
        (user['id'], total, request.form.get('notes', ''))
    ).lastrowid
    
    for v in validated:
        inv = v['inv']
        db.execute(
            'INSERT INTO order_items (order_id, inventory_id, item_name, quantity, unit, unit_price) VALUES (?,?,?,?,?,?)',
            (order_id, inv['id'], inv['item_name'], v['qty'], inv['unit'], inv['price_per_unit'])
        )
        db.execute('UPDATE inventory SET quantity = quantity - ? WHERE id=?', (v['qty'], inv['id']))
        
    db.commit()
    flash(f'Order #{order_id} placed successfully! Total: ₹{total:.2f}')
    return redirect(url_for('dashboard'))

@app.route('/order/<int:order_id>')
def order_detail(order_id):
    user = current_user()
    if not user: return redirect(url_for('index'))
    db = get_db()
    
    order = db.execute(
        'SELECT o.*, u.name as staff_name FROM orders o JOIN users u ON o.placed_by=u.id WHERE o.id=?',
        (order_id,)
    ).fetchone()
    
    items = db.execute('SELECT * FROM order_items WHERE order_id=?', (order_id,)).fetchall()
    return render_template('order_detail.html', user=user, order=order, items=items)
# ─── Delivery ─────────────────────────────────────────────────────────────────

@app.route('/order/accept/<int:order_id>', methods=['POST'])
def order_accept(order_id):
    guard = require_role('delivery')
    if guard: return guard
    user = current_user()
    db = get_db()
    db.execute(
        "UPDATE orders SET delivery_id=?, status='out_for_delivery' WHERE id=? AND status='confirmed'",
        (user['id'], order_id)
    )
    db.commit()
    flash(f'Order #{order_id} accepted for delivery.')
    return redirect(url_for('dashboard'))

@app.route('/order/deliver/<int:order_id>', methods=['POST'])
def order_deliver(order_id):
    guard = require_role('delivery')
    if guard: return guard
    user = current_user()
    db = get_db()
    db.execute(
        "UPDATE orders SET status='delivered' WHERE id=? AND delivery_id=?",
        (order_id, user['id'])
    )
    db.commit()
    flash(f'Order #{order_id} marked as delivered.')
    return redirect(url_for('dashboard'))

@app.route('/order/confirm/<int:order_id>', methods=['POST'])
def order_confirm(order_id):
    guard = require_role('school_staff', 'principal', 'admin')
    if guard: return guard
    db = get_db()
    db.execute("UPDATE orders SET status='confirmed' WHERE id=?", (order_id,))
    db.commit()
    flash(f'Order #{order_id} confirmed.')
    return redirect(url_for('dashboard'))

# ─── AI Demand Prediction (PM POSHAN compliant) ────────────────────────────────
#
# PM POSHAN nutritional norms (revised norms, letter F.No.1-4/2018-Desk(MDM) Dt.28-02-2019):
#
#   PRIMARY   (Class I–V):   450 kcal/day, 12g protein/day
#     → 100g food grain (rice/wheat), 25g pulses, 50g vegetables, 5g oil/fat per child
#
#   UPPER PRIMARY (Class VI–VIII): 700 kcal/day, 20g protein/day
#     → 150g food grain, 30g pulses, 75g vegetables, 7.5g oil/fat per child
#
# These are MINIMUM standards; actual procurement includes a 5% waste buffer.
# Minimum purchase quantities are enforced to prevent sub-economic orders.
#
# Supported AI providers (via POST body field "provider"):
#   "anthropic"  — Claude Sonnet (default; requires ANTHROPIC_API_KEY env var)
#   "openai"     — GPT-4o-mini  (requires OPENAI_API_KEY env var)
#   "gemini"     — Gemini 1.5 Flash (requires GEMINI_API_KEY env var)
#   "groq"       — Llama 3 via Groq (requires GROQ_API_KEY env var)
# ────────────────────────────────────────────────────────────────────────────────

# PM POSHAN official per-child-per-day norms (in grams; oil in mL per 100 students)
POSHAN_NORMS = [
    # (name, category, unit, primary_g_per_child, upper_g_per_child, min_purchase)
    # Food grains — per child in grams
    ('Rice',                'Grains',     'kg',  100,  150,  5.0),
    ('Dal (Lentil)',        'Grains',     'kg',   25,   30,  2.0),
    # Vegetables — per child in grams
    ('Tomatoes',            'Vegetables', 'kg',   20,   30,  1.0),
    ('Onions',              'Vegetables', 'kg',   15,   20,  1.0),
    ('Potatoes',            'Vegetables', 'kg',   25,   35,  2.0),
    ('Leafy Greens',        'Vegetables', 'kg',   10,   15,  0.5),
    # Oil — grams per child (7→7.5g upper primary per 2019 revision)
    ('Cooking Oil',         'Oils',       'L',     5,  7.5,  1.0),  # stored as g, returned as L (/1000)
    # Spices — grams per 100 students (not per child)
    ('Salt',                'Spices',     'kg',    2,    3,  0.5),   # g per 100 → kg/100 students
    ('Turmeric Powder',     'Spices',     'g',    50,   60, 50.0),
    ('Chili Powder',        'Spices',     'g',    30,   40, 50.0),
    ('Mustard Seeds',       'Spices',     'g',    20,   25, 30.0),
    ('Cumin Seeds',         'Spices',     'g',    15,   20, 30.0),
]


def _calc_quantity(name, unit, primary_g, upper_g, primary_att, upper_att):
    """
    Convert per-child gram norms to actual kg/L/g quantities.
    Oil and Salt are stored as per-100-students totals in the norms table.
    """
    if unit == 'g':
        # Spices: primary_g / upper_g are already per-100-students norms
        return (primary_g * primary_att / 100) + (upper_g * upper_att / 100)
    elif name in ('Cooking Oil', 'Salt'):
        # Oil: norm is mL per child (for oil) or g per 100 students (salt)
        # Cooking Oil: primary_g = 5 mL/child → convert to L
        return (primary_g * primary_att / 1000) + (upper_g * upper_att / 1000)
    else:
        # Grains and vegetables: norm in g per child → convert to kg
        return (primary_g * primary_att / 1000) + (upper_g * upper_att / 1000)


def _get_7day_avg(db, item_name):
    """Returns 7-day rolling average quantity ordered for this item (or None)."""
    row = db.execute('''
        SELECT AVG(oi.quantity) as avg_qty FROM order_items oi
        WHERE oi.item_name LIKE ? AND oi.order_id IN (
            SELECT id FROM orders WHERE created_at >= date('now','-7 days')
        )
    ''', (f'%{item_name.split(" ")[0]}%',)).fetchone()
    return float(row['avg_qty']) if row and row['avg_qty'] else None


def _call_ai_provider(provider, prompt):
    """
    Calls the specified AI provider.
    Provider must be one of: anthropic, openai, gemini, groq.
    API keys are read from environment variables.
    Returns the text response string.
    """
    import urllib.request, json as _json

    if provider == 'openai':
        api_key = os.environ.get('OPENAI_API_KEY','')
        if not api_key:
            return None
        payload = _json.dumps({
            'model': 'gpt-4o-mini',
            'max_tokens': 600,
            'messages': [{'role': 'user', 'content': prompt}]
        }).encode()
        req = urllib.request.Request(
            'https://api.openai.com/v1/chat/completions',
            data=payload,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = _json.loads(resp.read())
        return d['choices'][0]['message']['content']

    elif provider == 'gemini':
        api_key = os.environ.get('GEMINI_API_KEY','')
        if not api_key:
            return None
        url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}'
        payload = _json.dumps({'contents': [{'parts': [{'text': prompt}]}],
                               'generationConfig': {'maxOutputTokens': 600}}).encode()
        req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = _json.loads(resp.read())
        return d['candidates'][0]['content']['parts'][0]['text']

    elif provider == 'groq':
        api_key = os.environ.get('GROQ_API_KEY','')
        if not api_key:
            return None
        payload = _json.dumps({
            'model': 'llama3-8b-8192',
            'max_tokens': 600,
            'messages': [{'role': 'user', 'content': prompt}]
        }).encode()
        req = urllib.request.Request(
            'https://api.groq.com/openai/v1/chat/completions',
            data=payload,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = _json.loads(resp.read())
        return d['choices'][0]['message']['content']

    else:  # default: anthropic
        # When running inside Claude.ai artifacts the proxy handles auth.
        # In production Flask, set ANTHROPIC_API_KEY env var.
        api_key = os.environ.get('ANTHROPIC_API_KEY','')
        if not api_key:
            return None  # Fallback to formula-only mode
        payload = _json.dumps({
            'model': 'claude-sonnet-4-6',
            'max_tokens': 600,
            'messages': [{'role': 'user', 'content': prompt}]
        }).encode()
        req = urllib.request.Request(
            'https://api.anthropic.com/v1/messages',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'x-api-key': api_key,
                'anthropic-version': '2023-06-01'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = _json.loads(resp.read())
        return ''.join(c.get('text','') for c in d.get('content',[]))


@app.route('/ai/planner')
def ai_planner():
    """Full-page AI Food Demand Planner (PM POSHAN norms, attendance history, stock cross-check)."""
    user = current_user()
    if not user or user['role'] not in ('school_staff', 'principal'):
        return redirect(url_for('index'))
    return render_template('ai_planner.html', user=user)


@app.route('/ai/suggest', methods=['POST'])
def ai_suggest():
    """
    PM POSHAN-compliant AI demand prediction.

    Required POST JSON fields:
      attendance_primary  (int)  — students present in Class I–V today
      attendance_upper    (int)  — students present in Class VI–VIII today

    Optional:
      provider  (str)  — "anthropic" | "openai" | "gemini" | "groq" (default: "anthropic")

    Returns JSON:
      {
        "suggestions": [...],
        "ai_analysis": "...",
        "provider_used": "...",
        "norms_applied": "PM POSHAN revised 2019",
        "totals": { "children": N, "kcal_target": N, "protein_target_g": N }
      }
    """
    user = current_user()
    if not user or user['role'] not in ('school_staff', 'principal'):
        return jsonify({'error': 'Unauthorized'}), 403

    data             = request.get_json() or {}
    primary_att      = int(data.get('attendance_primary', data.get('attendance', 120)))
    upper_att        = int(data.get('attendance_upper',   80))
    provider         = data.get('provider', 'anthropic').lower()
    today            = date.today().isoformat()
    db               = get_db()

    # ── 1. FORMULA CALCULATION (PM POSHAN norms) ──────────────────────────────
    db.execute("DELETE FROM ai_suggestions WHERE DATE(generated_at)=?", (today,))

    suggestions = []
    for (name, cat, unit, primary_g, upper_g, min_qty) in POSHAN_NORMS:

        # Base quantity from today's attendance
        base_qty = _calc_quantity(name, unit, primary_g, upper_g, primary_att, upper_att)

        # 5% waste buffer (standard kitchen practice)
        with_buffer = base_qty * 1.05

        # Primary breakdown
        primary_qty = _calc_quantity(name, unit, primary_g, 0, primary_att, 0)
        upper_qty   = _calc_quantity(name, unit, 0, upper_g, 0, upper_att)

        # 7-day history weighting: 60% formula + 40% past average
        avg_past = _get_7day_avg(db, name)
        if avg_past:
            weighted_qty = round(with_buffer * 0.6 + avg_past * 0.4, 2)
        else:
            weighted_qty = round(with_buffer, 2)

        # Enforce minimum purchase quantity
        final_qty   = round(max(weighted_qty, min_qty), 2)
        min_enforced = final_qty > weighted_qty

        # Stock availability check
        stock_row = db.execute(
            'SELECT SUM(quantity) as total FROM inventory WHERE item_name LIKE ?',
            (f'%{name.split(" ")[0]}%',)
        ).fetchone()
        stock_avail = float(stock_row['total']) if stock_row and stock_row['total'] else 0.0
        stock_pct   = min(round((stock_avail / final_qty) * 100, 1), 100.0) if final_qty > 0 else 100.0
        if   stock_pct >= 100: stock_status = 'ok'
        elif stock_pct >= 50:  stock_status = 'warn'
        else:                  stock_status = 'critical'

        # Persist to DB
        db.execute(
            '''INSERT INTO ai_suggestions
               (item_name, category, suggested_qty, unit, basis_attendance)
               VALUES (?,?,?,?,?)''',
            (name, cat, final_qty, unit, primary_att + upper_att)
        )

        suggestions.append({
            'item':           name,
            'category':       cat,
            'unit':           unit,
            'qty':            final_qty,
            'primary_qty':    round(primary_qty, 2),
            'upper_qty':      round(upper_qty, 2),
            'history_avg':    round(avg_past, 2) if avg_past else None,
            'weighted_qty':   weighted_qty,
            'min_enforced':   min_enforced,
            'min_qty':        min_qty,
            'stock_available':stock_avail,
            'stock_pct':      stock_pct,
            'stock_status':   stock_status,
        })

    db.commit()

    # ── 2. AI NARRATIVE ANALYSIS ───────────────────────────────────────────────
    critical_items = [s['item'] for s in suggestions if s['stock_status'] == 'critical']
    item_lines     = '\n'.join(
        f"  {s['item']}: {s['qty']} {s['unit']} (stock: {s['stock_available']} {s['unit']}, {s['stock_status']})"
        for s in suggestions
    )
    ai_prompt = f"""You are a nutrition and procurement expert for India's PM POSHAN (Mid-Day Meal) scheme.

Today's school attendance:
- Primary (Class I–V): {primary_att} students
- Upper Primary (Class VI–VIII): {upper_att} students
- Total: {primary_att + upper_att} students

PM POSHAN norms applied:
- Primary: 450 kcal, 12g protein/child (100g rice, 25g dal, 50g vegetables, 5g oil)
- Upper Primary: 700 kcal, 20g protein/child (150g rice, 30g dal, 75g vegetables, 7.5g oil)

Calculated procurement (60% PM POSHAN formula + 40% 7-day history, 5% waste buffer, minimums enforced):
{item_lines}

{f'⚠ CRITICAL STOCK SHORTAGES — immediate restocking needed: {", ".join(critical_items)}' if critical_items else ''}

Write 3–4 concise sentences for school kitchen staff covering:
1. How today's attendance compares to the historical average and what that means for quantities.
2. Any nutritional balance concern based on the menu (e.g. protein adequacy, iron from greens).
3. What to prioritise restocking first and why.
Keep it practical and in plain English. No bullet points."""

    ai_text    = None
    provider_used = provider
    try:
        ai_text = _call_ai_provider(provider, ai_prompt)
    except Exception as e:
        app.logger.warning(f'AI provider {provider} failed: {e}')
        ai_text = None
        provider_used = 'formula_only'

    if not ai_text:
        provider_used = 'formula_only'
        ai_text = (
            f"Today's procurement covers {primary_att + upper_att} children meeting PM POSHAN norms "
            f"({primary_att} primary @ 450 kcal, {upper_att} upper primary @ 700 kcal). "
            + (f"Critical restock needed for: {', '.join(critical_items)}. " if critical_items else "All items have adequate stock. ")
            + "Quantities are calculated using the official PM POSHAN formula weighted with your 7-day order history."
        )

    return jsonify({
        'suggestions':    suggestions,
        'ai_analysis':    ai_text,
        'provider_used':  provider_used,
        'norms_applied':  'PM POSHAN revised norms (F.No.1-4/2018-Desk(MDM) Dt.28-02-2019)',
        'totals': {
            'children':         primary_att + upper_att,
            'primary_att':      primary_att,
            'upper_att':        upper_att,
            'kcal_target':      (primary_att * 450) + (upper_att * 700),
            'protein_target_g': (primary_att * 12)  + (upper_att * 20),
        }
    })


@app.route('/api/inventory')
@app.route('/api/inventory')
def api_inventory():
    db = get_db()
    items = db.execute('''
        SELECT i.*,
               c.name AS category,
               u.name AS merchant_name
        FROM inventory i
        JOIN categories c ON i.category_id = c.id
        JOIN users u ON i.merchant_id = u.id
        WHERE i.quantity > 0
        ORDER BY c.name, i.item_name
    ''').fetchall()

    return jsonify([dict(r) for r in items])


@app.route('/api/attendance/history')
def api_attendance_history():
    """Returns 7-day attendance history inferred from order volumes (proxy metric)."""
    user = current_user()
    if not user: return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    rows = db.execute('''
        SELECT DATE(generated_at) as day,
               CAST(AVG(basis_attendance) AS INTEGER) as total_att,
               MAX(generated_at) as last_generated
        FROM ai_suggestions
        WHERE generated_at >= date('now','-7 days')
        GROUP BY day ORDER BY day
    ''').fetchall()
    return jsonify([dict(r) for r in rows])


if __name__ == '__main__':
    app.run(debug=True, port=5000)