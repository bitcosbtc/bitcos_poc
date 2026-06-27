from app.database import SessionLocal, engine, Base
from app.models.user import User
from app.utils.security import get_password_hash

print("=" * 50)
print("ADMIN USER SETUP")
print("=" * 50)

try:
    
    Base.metadata.create_all(bind=engine)
    print("Database tables created/verified")

    db = SessionLocal()

    existing_admin = db.query(User).filter(User.username == "admin").first()

    if existing_admin:
        print(f"\n Admin found:")
        print(f"   Username: {existing_admin.username}")
        print(f"   Email: {existing_admin.email}")
        print(f"   Active: {existing_admin.is_active}")
        print(f"   Role: {existing_admin.role}")
        
        # Force fix all fields
        existing_admin.is_active = True
        existing_admin.role = "admin"
        existing_admin.email = "admin@gmail.com"
        existing_admin.password_hash = get_password_hash("admin123")
        db.commit()
        db.refresh(existing_admin)
        
        print(f"\n Admin user FIXED!")
        print(f"   Active: {existing_admin.is_active}")
        print(f"   Role: {existing_admin.role}")
    else:
        print("\n No admin found. Creating new admin user...")
        admin = User(
            username="admin1",
            email="test@gmail.com",
            password_hash=get_password_hash("test123"),
            role="admin",
            is_active=True
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        print(f" Admin user created successfully!")
        print(f"   ID: {admin.id}")
        print(f"   Username: {admin.username}")
        print(f"   Email: {admin.email}")

    print("\n" + "=" * 50)
    print("LOGIN CREDENTIALS")
    print("=" * 50)
    print("  Username: admin")
    print("  Password: admin123")
    print("=" * 50)

except Exception as e:
    print(f"\n ERROR: {e}")
    import traceback
    traceback.print_exc()
    if 'db' in locals():
        db.rollback()
finally:
    if 'db' in locals():
        db.close()
        print("\n Database connection closed")