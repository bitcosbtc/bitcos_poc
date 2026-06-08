from cryptography.fernet import Fernet
from ..config import settings

class EncryptionService:
    def __init__(self):
        self.cipher = Fernet(settings.ENCRYPTION_KEY.encode())
    
    def encrypt(self, data: str) -> str:
        return self.cipher.encrypt(data.encode()).decode()
    
    def decrypt(self, encrypted_data: str) -> str:
        return self.cipher.decrypt(encrypted_data.encode()).decode()

encryption_service = EncryptionService()