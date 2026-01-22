# models.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

# Initialize the database
db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    # In production, we should hash passwords. For this prototype, we store plain text for simplicity.
    # We can upgrade to werkzeug.security in Sprint 2.
    password = db.Column(db.String(128)) 
    role = db.Column(db.String(20), default='user') # 'admin' or 'user'
    weekly_allowance_amount = db.Column(db.Float, default=10.0)
    last_allowance_date = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship to transactions
    transactions = db.relationship('Transaction', backref='user', lazy=True)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    amount = db.Column(db.Float, nullable=False) # Negative for spend, Positive for earn
    description = db.Column(db.String(200)) # The "Note"
    category = db.Column(db.String(50), default='Others') # Default category
    
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)