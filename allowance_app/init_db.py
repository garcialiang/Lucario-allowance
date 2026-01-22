# init_db.py
from app import app, db
from models import User
from datetime import datetime

# --- CONFIGURATION (HARDCODE CREDENTIALS HERE) ---
ADMIN_USER = 'admin'
ADMIN_PASS = 'adminpassword'

SON_USER = 'JINYU'          # <--- Change this to your son's preferred username
SON_PASS = 'lovejinyu' # <--- Change this to his password
WEEKLY_RATE = 1.0          # <--- Set the default allowance rate
# -------------------------------------------------

with app.app_context():
    # This creates the tables if they don't exist
    db.create_all()
    
    # 1. Setup Admin
    admin = User.query.filter_by(role='admin').first()
    if not admin:
        admin = User(username=ADMIN_USER, role='admin')
        db.session.add(admin)
        print("Admin account created.")
    
    # Always ensure admin password is set to what's in the config
    admin.password = ADMIN_PASS
    admin.username = ADMIN_USER

    # 2. Setup Son
    son = User.query.filter_by(role='user').first()
    if not son:
        son = User(role='user', last_allowance_date=datetime.utcnow())
        db.session.add(son)
        print("Son account created.")
    
    # Update Son's details to match your hardcoded config
    son.username = SON_USER
    son.password = SON_PASS
    son.weekly_allowance_amount = WEEKLY_RATE

    db.session.commit()
    print(f"Database Updated! Son's login is now: {SON_USER} / {SON_PASS}")