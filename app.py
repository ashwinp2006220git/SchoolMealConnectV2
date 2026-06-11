from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from database import init_db, get_db
from datetime import datetime, date
import json, hashlib, os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'schoolmeal-dev-secret-2024')

@app.before_request
def setup():
    init_db()

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def current_user():
    return session.get('user')

def require_role(*roles):
    user = current_user()
    if not user or user['role'] not in roles:
        return redirect(url_for('index'))
    return None

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
        role     = request.form['role']
        name     = request.form['name'].strip()
        phone    = request.form.get('phone', '').strip()
        if role == 'admin':
            flash('Admin accounts cannot be created via registration.')
            return redirect(url_for('register'))
        db = get_db()
        if db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone():
            flash('Username already taken.')
            return redirect(url_for('register'))
        db.execute(
            'INSERT INTO users (username, password_hash, role, name, phone) VALUES (?,?,?,?,?)',
            (username, hash_password(password), role, name, phone)
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
    users      = db.execute('SELECT * FROM users ORDER BY role, name').fetchall()
    orders     = db.execute('''
        SELECT o.*, u.name AS staff_name FROM orders o
        JOIN users u ON o.placed_by = u.id
        ORDER BY o.created_at DESC
    ''').fetchall()
    inventory  = db.execute('''
        SELECT i.*, u.name AS merchant_name FROM inventory i
        JOIN users u ON i.merchant_id = u.id
        ORDER BY u.name, i.category, i.item_name
    ''').fetchall()
    stats = {
        'total_users':   db.execute('SELECT COUNT(*) as c FROM users').fetchone()['c'],
        'total_orders':  db.execute('SELECT COUNT(*) as c FROM orders').fetchone()['c'],
        'total_spend':   db.execute('SELECT COALESCE(SUM(total_amount),0) as t FROM orders').fetchone()['t'],
        'active_items':  db.execute('SELECT COUNT(*) as c FROM inventory WHERE quantity>0').fetchone()['c'],
    }
    return render_template('admin_dashboard.html',
        user=user, users=users, orders=orders, inventory=inventory, stats=stats)

# ─── Admin: user management ────────────────────────────────────────────────────

@app.route('/admin/user/add', methods=['POST'])
def admin_user_add():
    guard = require_role('admin')
    if guard: return guard
    db = get_db()
    username = request.form['username'].strip()
    if db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone():
        flash('Username already taken.')
        return redirect(url_for('dashboard'))
    db.execute(
        'INSERT INTO users (username, password_hash, role, name, phone) VALUES (?,?,?,?,?)',
        (username, hash_password(request.form['password']),
         request.form['role'], request.form['name'].strip(),
         request.form.get('phone', '').strip())
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
    # Reassign or nullify references before deleting
    db.execute('DELETE FROM inventory WHERE merchant_id=?', (uid,))
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

# ─── Admin: order management ───────────────────────────────────────────────────

@app.route('/admin/order/delete/<int:order_id>', methods=['POST'])
def admin_order_delete(order_id):
    guard = require_role('admin')
    if guard: return guard
    db = get_db()
    # Restore inventory quantities before deleting
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
    db.execute('DELETE FROM inventory WHERE id=?', (item_id,))
    db.commit()
    flash('Inventory item removed.')
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
    return render_template('principal_dashboard.html',
        user=user, orders=orders, total_today=total_today,
        pending=pending, delivered=delivered,
        top_merchants=top_merchants, recent_spend=recent_spend)

# ─── Staff dashboard ───────────────────────────────────────────────────────────

def _staff_dashboard(db, user):
    items = db.execute('''
        SELECT i.*, u.name AS merchant_name, u.phone AS merchant_phone
        FROM inventory i JOIN users u ON i.merchant_id = u.id
        WHERE i.quantity > 0 AND u.is_active = 1
        ORDER BY i.category, i.item_name
    ''').fetchall()
    my_orders = db.execute(
        'SELECT * FROM orders WHERE placed_by=? ORDER BY created_at DESC LIMIT 20',
        (user['id'],)
    ).fetchall()
    ai_suggestions = db.execute(
        'SELECT * FROM ai_suggestions WHERE DATE(generated_at)=? ORDER BY item_name',
        (date.today().isoformat(),)
    ).fetchall()
    return render_template('staff_dashboard.html',
        user=user, items=items, my_orders=my_orders, ai_suggestions=ai_suggestions)

# ─── Merchant dashboard ────────────────────────────────────────────────────────

def _merchant_dashboard(db, user):
    my_items = db.execute(
        'SELECT * FROM inventory WHERE merchant_id=? ORDER BY category, item_name',
        (user['id'],)
    ).fetchall()
    my_orders = db.execute('''
        SELECT oi.*, o.id as order_id, o.status, o.created_at, u.name as staff_name
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.id
        JOIN inventory i ON oi.inventory_id = i.id
        JOIN users u ON o.placed_by = u.id
        WHERE i.merchant_id=?
        ORDER BY o.created_at DESC LIMIT 30
    ''', (user['id'],)).fetchall()
    return render_template('merchant_dashboard.html',
        user=user, my_items=my_items, my_orders=my_orders)

# ─── Delivery dashboard ────────────────────────────────────────────────────────

def _delivery_dashboard(db, user):
    available = db.execute(
        "SELECT o.*, u.name as staff_name FROM orders o JOIN users u ON o.placed_by=u.id WHERE o.status='confirmed' AND o.delivery_id IS NULL ORDER BY o.created_at"
    ).fetchall()
    my_jobs = db.execute(
        "SELECT o.*, u.name as staff_name FROM orders o JOIN users u ON o.placed_by=u.id WHERE o.delivery_id=? ORDER BY o.created_at DESC LIMIT 20",
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
    db.execute(
        'INSERT INTO inventory (merchant_id, item_name, category, unit, quantity, price_per_unit) VALUES (?,?,?,?,?,?)',
        (user['id'], request.form['item_name'], request.form['category'],
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
    db.execute('DELETE FROM inventory WHERE id=? AND merchant_id=?', (item_id, user['id']))
    db.commit()
    return redirect(url_for('dashboard'))

# ─── Orders (School Staff) ────────────────────────────────────────────────────

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

    # ── Stock validation: check every item before touching anything ──
    errors = []
    validated = []
    for item in cart:
        inv = db.execute('SELECT * FROM inventory WHERE id=?', (item['id'],)).fetchone()
        if not inv:
            errors.append(f"Item #{item['id']} no longer exists.")
            continue
        requested = float(item['qty'])
        available = float(inv['quantity'])
        if requested <= 0:
            errors.append(f"'{inv['item_name']}': quantity must be greater than zero.")
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

    # ── All good — create order ──
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

# ─── AI Demand Prediction ──────────────────────────────────────────────────────

@app.route('/ai/suggest', methods=['POST'])
def ai_suggest():
    user = current_user()
    if not user or user['role'] not in ('school_staff', 'principal', 'admin'):
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    data = request.get_json()
    attendance = int(data.get('attendance', 200))
    today = date.today().isoformat()
    db.execute("DELETE FROM ai_suggestions WHERE DATE(generated_at)=?", (today,))
    base_per_100 = {
        'Rice':         ('kg', 5.0,  'Grains'),
        'Dal (Lentil)': ('kg', 2.5,  'Grains'),
        'Tomatoes':     ('kg', 2.0,  'Vegetables'),
        'Onions':       ('kg', 1.5,  'Vegetables'),
        'Potatoes':     ('kg', 3.0,  'Vegetables'),
        'Spinach':      ('kg', 1.0,  'Vegetables'),
        'Cooking Oil':  ('L',  0.8,  'Oils'),
        'Salt':         ('kg', 0.3,  'Spices'),
        'Turmeric':     ('g',  50.0, 'Spices'),
        'Chili Powder': ('g',  40.0, 'Spices'),
        'Mustard Seeds':('g',  30.0, 'Spices'),
    }
    suggestions = []
    for item, (unit, qty_per_100, cat) in base_per_100.items():
        suggested_qty = round((qty_per_100 * attendance) / 100, 2)
        avg_row = db.execute('''
            SELECT AVG(oi.quantity) as avg_qty FROM order_items oi
            WHERE oi.item_name LIKE ? AND oi.order_id IN (
                SELECT id FROM orders WHERE created_at >= date('now','-7 days')
            )
        ''', (f'%{item}%',)).fetchone()
        avg_past = avg_row['avg_qty'] if avg_row and avg_row['avg_qty'] else None
        if avg_past:
            suggested_qty = round((suggested_qty * 0.6 + avg_past * 0.4), 2)
        db.execute(
            'INSERT INTO ai_suggestions (item_name, category, suggested_qty, unit, basis_attendance) VALUES (?,?,?,?,?)',
            (item, cat, suggested_qty, unit, attendance)
        )
        suggestions.append({'item': item, 'qty': suggested_qty, 'unit': unit, 'category': cat})
    db.commit()
    return jsonify({'suggestions': suggestions, 'attendance': attendance})

@app.route('/api/inventory')
def api_inventory():
    db = get_db()
    items = db.execute('''
        SELECT i.*, u.name AS merchant_name FROM inventory i
        JOIN users u ON i.merchant_id=u.id
        WHERE i.quantity > 0 AND u.is_active = 1
        ORDER BY i.category, i.item_name
    ''').fetchall()
    return jsonify([dict(r) for r in items])

if __name__ == '__main__':
    app.run(debug=True, port=5000)
