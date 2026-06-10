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

# ─── Auth ─────────────────────────────────────────────────────────────────────

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
        'SELECT * FROM users WHERE username=? AND password_hash=?',
        (username, hash_password(password))
    ).fetchone()
    if user:
        session['user'] = dict(user)
        return redirect(url_for('dashboard'))
    flash('Invalid username or password.')
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        role     = request.form['role']
        name     = request.form['name'].strip()
        phone    = request.form.get('phone','').strip()
        db = get_db()
        existing = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
        if existing:
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

# ─── Dashboard router ─────────────────────────────────────────────────────────

@app.route('/dashboard')
def dashboard():
    user = current_user()
    if not user:
        return redirect(url_for('index'))
    role = user['role']
    db = get_db()
    if role == 'principal':
        return _principal_dashboard(db, user)
    elif role == 'school_staff':
        return _staff_dashboard(db, user)
    elif role == 'merchant':
        return _merchant_dashboard(db, user)
    elif role == 'delivery':
        return _delivery_dashboard(db, user)
    return redirect(url_for('index'))

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

def _staff_dashboard(db, user):
    items = db.execute('''
        SELECT i.*, u.name AS merchant_name, u.phone AS merchant_phone
        FROM inventory i JOIN users u ON i.merchant_id = u.id
        WHERE i.quantity > 0
        ORDER BY i.category, i.item_name
    ''').fetchall()
    my_orders = db.execute('''
        SELECT * FROM orders WHERE placed_by=? ORDER BY created_at DESC LIMIT 20
    ''', (user['id'],)).fetchall()
    ai_suggestions = db.execute(
        'SELECT * FROM ai_suggestions WHERE DATE(generated_at)=? ORDER BY item_name',
        (date.today().isoformat(),)
    ).fetchall()
    return render_template('staff_dashboard.html',
        user=user, items=items, my_orders=my_orders, ai_suggestions=ai_suggestions)

def _merchant_dashboard(db, user):
    my_items = db.execute(
        'SELECT * FROM inventory WHERE merchant_id=? ORDER BY category, item_name',
        (user['id'],)
    ).fetchall()
    my_orders = db.execute('''
        SELECT oi.*, o.status, o.created_at, u.name as staff_name
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.id
        JOIN inventory i ON oi.inventory_id = i.id
        JOIN users u ON o.placed_by = u.id
        WHERE i.merchant_id=?
        ORDER BY o.created_at DESC LIMIT 30
    ''', (user['id'],)).fetchall()
    return render_template('merchant_dashboard.html',
        user=user, my_items=my_items, my_orders=my_orders)

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

# ─── Inventory (Merchant) ─────────────────────────────────────────────────────

@app.route('/inventory/add', methods=['POST'])
def inventory_add():
    user = current_user()
    if not user or user['role'] != 'merchant': return redirect(url_for('index'))
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
    user = current_user()
    if not user or user['role'] != 'merchant': return redirect(url_for('index'))
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
    user = current_user()
    if not user or user['role'] != 'merchant': return redirect(url_for('index'))
    db = get_db()
    db.execute('DELETE FROM inventory WHERE id=? AND merchant_id=?', (item_id, user['id']))
    db.commit()
    return redirect(url_for('dashboard'))

# ─── Orders (School Staff) ────────────────────────────────────────────────────

@app.route('/order/place', methods=['POST'])
def order_place():
    user = current_user()
    if not user or user['role'] != 'school_staff': return redirect(url_for('index'))
    db   = get_db()
    cart = json.loads(request.form.get('cart', '[]'))
    if not cart:
        flash('Your order is empty.')
        return redirect(url_for('dashboard'))
    total = 0
    for item in cart:
        inv = db.execute('SELECT * FROM inventory WHERE id=?', (item['id'],)).fetchone()
        if inv:
            total += float(inv['price_per_unit']) * float(item['qty'])
    order_id = db.execute(
        'INSERT INTO orders (placed_by, total_amount, notes) VALUES (?,?,?)',
        (user['id'], total, request.form.get('notes',''))
    ).lastrowid
    for item in cart:
        inv = db.execute('SELECT * FROM inventory WHERE id=?', (item['id'],)).fetchone()
        if inv:
            db.execute(
                'INSERT INTO order_items (order_id, inventory_id, item_name, quantity, unit, unit_price) VALUES (?,?,?,?,?,?)',
                (order_id, item['id'], inv['item_name'], item['qty'], inv['unit'], inv['price_per_unit'])
            )
            db.execute('UPDATE inventory SET quantity = quantity - ? WHERE id=?', (item['qty'], item['id']))
    db.commit()
    flash(f'Order #{order_id} placed successfully! Total: ₹{total:.2f}')
    return redirect(url_for('dashboard'))

@app.route('/order/<int:order_id>')
def order_detail(order_id):
    user = current_user()
    if not user: return redirect(url_for('index'))
    db = get_db()
    order = db.execute('SELECT o.*, u.name as staff_name FROM orders o JOIN users u ON o.placed_by=u.id WHERE o.id=?', (order_id,)).fetchone()
    items = db.execute('SELECT * FROM order_items WHERE order_id=?', (order_id,)).fetchall()
    return render_template('order_detail.html', user=user, order=order, items=items)

# ─── Delivery ─────────────────────────────────────────────────────────────────

@app.route('/order/accept/<int:order_id>', methods=['POST'])
def order_accept(order_id):
    user = current_user()
    if not user or user['role'] != 'delivery': return redirect(url_for('index'))
    db = get_db()
    db.execute("UPDATE orders SET delivery_id=?, status='out_for_delivery' WHERE id=? AND status='confirmed'",
               (user['id'], order_id))
    db.commit()
    flash(f'Order #{order_id} accepted for delivery.')
    return redirect(url_for('dashboard'))

@app.route('/order/deliver/<int:order_id>', methods=['POST'])
def order_deliver(order_id):
    user = current_user()
    if not user or user['role'] != 'delivery': return redirect(url_for('index'))
    db = get_db()
    db.execute("UPDATE orders SET status='delivered' WHERE id=? AND delivery_id=?",
               (order_id, user['id']))
    db.commit()
    flash(f'Order #{order_id} marked as delivered.')
    return redirect(url_for('dashboard'))

@app.route('/order/confirm/<int:order_id>', methods=['POST'])
def order_confirm(order_id):
    user = current_user()
    if not user or user['role'] not in ('school_staff','principal'): return redirect(url_for('index'))
    db = get_db()
    db.execute("UPDATE orders SET status='confirmed' WHERE id=?", (order_id,))
    db.commit()
    flash(f'Order #{order_id} confirmed.')
    return redirect(url_for('dashboard'))

# ─── AI Demand Prediction ──────────────────────────────────────────────────────

@app.route('/ai/suggest', methods=['POST'])
def ai_suggest():
    """Simple ML-style demand prediction based on attendance and past usage."""
    user = current_user()
    if not user or user['role'] not in ('school_staff','principal'):
        return jsonify({'error': 'Unauthorized'}), 403
    db = get_db()
    data = request.get_json()
    attendance = int(data.get('attendance', 200))
    # Clear old suggestions for today
    today = date.today().isoformat()
    db.execute("DELETE FROM ai_suggestions WHERE DATE(generated_at)=?", (today,))
    # Base quantities per 100 students
    base_per_100 = {
        'Rice':        ('kg',  5.0,   'Grains'),
        'Dal (Lentil)':('kg',  2.5,   'Grains'),
        'Tomatoes':    ('kg',  2.0,   'Vegetables'),
        'Onions':      ('kg',  1.5,   'Vegetables'),
        'Potatoes':    ('kg',  3.0,   'Vegetables'),
        'Spinach':     ('kg',  1.0,   'Vegetables'),
        'Cooking Oil': ('L',   0.8,   'Oils'),
        'Salt':        ('kg',  0.3,   'Spices'),
        'Turmeric':    ('g',  50.0,   'Spices'),
        'Chili Powder':('g',  40.0,   'Spices'),
        'Mustard Seeds':('g', 30.0,  'Spices'),
    }
    suggestions = []
    for item, (unit, qty_per_100, cat) in base_per_100.items():
        suggested_qty = round((qty_per_100 * attendance) / 100, 2)
        # Check past 7 days average
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
        JOIN users u ON i.merchant_id=u.id WHERE i.quantity > 0
        ORDER BY i.category, i.item_name
    ''').fetchall()
    return jsonify([dict(r) for r in items])

if __name__ == '__main__':
    app.run(debug=True, port=5000)
