from app.database import SessionLocal, engine, Base
from app.models.user import User
from app.utils.security import get_password_hash

Base.metadata.create_all(bind=engine)
db = SessionLocal()

accounts = [
    {"username": "admin", "email": "admin@gmail.com", "role": "admin", "pass": "admin123"},
    {"username": "divyanshu", "email": "divyanshu@bitcosbtc.com", "role": "admin", "pass": "admin123"},
]

for acc in accounts:
    user = db.query(User).filter(User.username == acc["username"]).first()
    if user:
        user.password_hash = get_password_hash(acc["pass"])
        user.is_active = True
        user.role = acc["role"]
        user.email = acc["email"]
        print(f"Updated user: {acc['username']}")
    else:
        user = User(
            username=acc["username"],
            email=acc["email"],
            password_hash=get_password_hash(acc["pass"]),
            role=acc["role"],
            is_active=True
        )
        db.add(user)
        print(f"Created user: {acc['username']}")

db.commit()
all_users = db.query(User).all()
print("\nAll database users:")
for u in all_users:
    print(f" - ID: {u.id}, Username: '{u.username}', Email: '{u.email}', Role: '{u.role}', Active: {u.is_active}")
db.close()
