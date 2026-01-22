# app.py
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from models import db, User, Transaction
from datetime import datetime, timedelta
import pandas as pd
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'mysecretkey' # Needed for session management
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///allowance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def get_balance(user):
    """Sum of all transactions for a user."""
    transactions = Transaction.query.filter_by(user_id=user.id).all()
    return sum(t.amount for t in transactions)

# --- ROUTES ---

# --- HELPER: Check for duplicates ---
def transaction_exists(user_id, date, amount, description):
    """Returns True if a transaction with exact details already exists."""
    # We strip time from date comparison if you only care about the day
    existing = Transaction.query.filter_by(
        user_id=user_id,
        amount=amount,
        description=description
    ).filter(
        db.func.date(Transaction.date) == date.date()
    ).first()
    return existing is not None

# --- HELPER: Smart Monday Updates ---
def update_allowance(user):
    """
    Adds allowance for every Monday that has passed since the last update.
    """
    if user.role != 'user': return 
    
    # 1. Get the starting point
    last_date = user.last_allowance_date
    if not last_date:
        # If new user, set start date to today (no back-pay)
        user.last_allowance_date = datetime.utcnow()
        db.session.commit()
        return

    today = datetime.utcnow()
    
    # 2. Logic: Loop forward day-by-day or week-by-week
    # We want to find the *next* Monday after the last payment.
    # weekday(): Monday is 0, Sunday is 6
    
    # Move cursor forward to the very next day
    cursor_date = last_date + timedelta(days=1)
    
    # Advance cursor until we hit a Monday (0)
    while cursor_date.weekday() != 0:
        cursor_date += timedelta(days=1)
        
    # Now cursor_date is the first Monday AFTER the last payment.
    # Check if that Monday has already happened (is in the past/today)
    updates_made = False
    
    while cursor_date <= today:
        # It's a Monday in the past! Pay the kid.
        new_allowance = Transaction(
            date=cursor_date,
            amount=user.weekly_allowance_amount,
            description="Weekly allowance",
            category="allowance",
            user_id=user.id
        )
        db.session.add(new_allowance)
        
        # Update the user's "Paid Until" date
        user.last_allowance_date = cursor_date
        updates_made = True
        
        # Jump to next week
        cursor_date += timedelta(weeks=1)
        
    if updates_made:
        db.session.commit()
        flash("System updated missed weekly allowances.")

# --- ROUTES ---

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    # 1. DETERMINE TARGET & TRIGGER ALLOWANCE
    target_user = current_user
    
    if current_user.role == 'admin':
        # If Admin logs in, find the son and run the allowance check
        son = User.query.filter_by(role='user').first()
        if son:
            update_allowance(son)
            target_user = son
    else:
        # If Son logs in, check his own allowance
        update_allowance(current_user)

    # 2. Get total balance
    balance = get_balance(target_user)

    # ... (The rest of your index function filtering logic remains the same) ...
    # Be sure to keep the month filtering code we wrote in Sprint 4 here!
    
    # For brevity, I am repeating the standard query logic below so you can copy-paste safely:
    
    dates = db.session.query(Transaction.date).filter_by(user_id=target_user.id).all()
    available_months = sorted(list(set([d[0].strftime('%Y-%m') for d in dates])), reverse=True)

    selected_month = request.args.get('month')
    query = Transaction.query.filter_by(user_id=target_user.id)

    if selected_month and selected_month != 'recent':
        year, month = map(int, selected_month.split('-'))
        query = query.filter(db.extract('year', Transaction.date) == year,
                             db.extract('month', Transaction.date) == month)
        view_title = f"History for {selected_month}"
    else:
        three_months_ago = datetime.utcnow() - timedelta(days=90)
        query = query.filter(Transaction.date >= three_months_ago)
        view_title = "Last 3 Months"
        selected_month = 'recent'

    transactions = query.order_by(Transaction.date.desc()).all()

    return render_template('dashboard.html', 
                           user=current_user, 
                           target_user=target_user, 
                           balance=balance, 
                           transactions=transactions,
                           available_months=available_months,
                           selected_month=selected_month,
                           view_title=view_title)

@app.route('/add_transaction', methods=['POST'])
@login_required
def add_transaction():
    if current_user.role != 'admin':
        return "Unauthorized", 403
        
    amount = float(request.form.get('amount'))
    description = request.form.get('description')
    category = request.form.get('category')
    user_id = request.form.get('user_id')
    date_str = request.form.get('date') # Get the date string from the form
    
    # Parse the date, or default to now if empty
    if date_str:
        try:
            trans_date = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            trans_date = datetime.utcnow()
    else:
        trans_date = datetime.utcnow()

    # CHECK DUPLICATE
    if transaction_exists(user_id, trans_date, amount, description):
        flash('Skipped: Duplicate transaction detected.')
    else:
        new_trans = Transaction(
            date=trans_date,
            amount=amount,
            description=description,
            category=category,
            user_id=user_id
        )
        db.session.add(new_trans)
        db.session.commit()
        flash('Transaction added successfully.')
        
    return redirect(url_for('index'))

@app.route('/upload_csv', methods=['POST'])
@login_required
def upload_csv():
    if current_user.role != 'admin': return "Unauthorized", 403
    # ... (File checks remain the same) ...
    file = request.files['file']
    if file:
        try:
            df = pd.read_csv(file)
            df.columns = [c.strip().lower() for c in df.columns]
            
            target_user = User.query.filter_by(role='user').first()
            count = 0
            skipped = 0
            
            for index, row in df.iterrows():
                try:
                    trans_date = pd.to_datetime(row['date'], dayfirst=False).to_pydatetime()
                except: continue 

                amount = float(row['amount'])
                description = str(row['note'])
                cat = str(row['category']) if 'category' in df.columns and pd.notna(row['category']) else "Others"

                # CHECK DUPLICATE
                if transaction_exists(target_user.id, trans_date, amount, description):
                    skipped += 1
                    continue

                new_trans = Transaction(
                    date=trans_date,
                    amount=amount,
                    description=description,
                    category=cat,
                    user_id=target_user.id
                )
                db.session.add(new_trans)
                count += 1
            
            db.session.commit()
            flash(f"Imported {count} transactions. Skipped {skipped} duplicates.")
            
        except Exception as e:
            flash(f"Error: {str(e)}")
            
    return redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.password == password:
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash('Login failed. Check details.')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    if current_user.role != 'admin':
        return "Unauthorized", 403
    
    # Get the son's user object (assuming username 'son' or logic to find child)
    son = User.query.filter_by(role='user').first()
    
    if son:
        new_allowance = request.form.get('weekly_allowance')
        if new_allowance:
            son.weekly_allowance_amount = float(new_allowance)
            db.session.commit()
            flash(f"Allowance updated to ${son.weekly_allowance_amount}")
            
    return redirect(url_for('index'))

@app.route('/delete_transaction/<int:id>')
@login_required
def delete_transaction(id):
    if current_user.role != 'admin':
        return "Unauthorized", 403
        
    transaction = Transaction.query.get_or_404(id)
    
    # Optional: Security check to ensure we don't delete another user's data 
    # (though right now we only have one child, so it's fine)
    
    db.session.delete(transaction)
    db.session.commit()
    flash('Transaction deleted.')
    return redirect(url_for('index'))

@app.route('/analytics')
@login_required
def analytics():
    target_user = current_user
    if current_user.role == 'admin':
        target_user = User.query.filter_by(role='user').first()
    
    # 1. Base Query
    query = Transaction.query.filter_by(user_id=target_user.id)
    
    # 2. Check for Date Filters in URL
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')
    
    # Apply Start Date Filter
    if start_str:
        try:
            s_date = datetime.strptime(start_str, '%Y-%m-%d')
            query = query.filter(Transaction.date >= s_date)
        except ValueError:
            pass # Ignore invalid dates

    # Apply End Date Filter
    if end_str:
        try:
            e_date = datetime.strptime(end_str, '%Y-%m-%d')
            # Set time to end of day (23:59:59) so we capture transactions on that day
            e_date = e_date.replace(hour=23, minute=59, second=59)
            query = query.filter(Transaction.date <= e_date)
        except ValueError:
            pass

    transactions = query.all()
    
    # 3. Process Data (Same as before)
    spending_by_category = {}
    earnings_by_category = {} 
    total_earned = 0
    total_spent = 0
    
    for t in transactions:
        cat = t.category if t.category else "Others"
        cat = cat.strip().title() 

        if t.amount < 0:
            abs_amount = abs(t.amount)
            total_spent += abs_amount
            spending_by_category[cat] = spending_by_category.get(cat, 0) + abs_amount
        else:
            total_earned += t.amount
            earnings_by_category[cat] = earnings_by_category.get(cat, 0) + t.amount

    # Pass the current filter values back to UI so inputs stay filled
    return render_template('analytics.html', 
                           user=current_user,
                           spending_data=spending_by_category,
                           earnings_data=earnings_by_category, 
                           earned=total_earned, 
                           spent=total_spent,
                           start_date=start_str, # <--- Pass these back
                           end_date=end_str)     # <--- Pass these back

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)