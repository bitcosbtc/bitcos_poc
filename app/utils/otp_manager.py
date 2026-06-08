import pyotp
from typing import Optional

class OTPManager:
    @staticmethod
    def generate_otp(secret: str) -> str:
        """
        Generate a 6-digit TOTP code using the provided secret.
        """
        try:
            totp = pyotp.TOTP(secret)
            return totp.now()
        except Exception as e:
            print(f"Error generating OTP: {e}")
            return "000000"

    @staticmethod
    def get_remaining_seconds(secret: str) -> int:
        """
        Get remaining seconds until the current OTP expires.
        """
        try:
            totp = pyotp.TOTP(secret)
            # TOTP works in 30-second intervals
            return 30 - (int(pyotp.datetime.datetime.now().timestamp()) % 30)
        except Exception:
            return 0

otp_manager = OTPManager()
