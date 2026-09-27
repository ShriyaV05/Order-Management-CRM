import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

# PBKDF2-SHA256 password hashing with random salt
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    iterations = 100_000
    derived = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), iterations)
    return f"{salt}${iterations}${derived.hex()}"

def verify_password(password: str, stored_hash: str) -> bool:
    try:
        parts = stored_hash.split('$')
        if len(parts) == 3:
            salt, iterations_str, derived_hex = parts
            iterations = int(iterations_str)
        elif len(parts) == 2:
            salt, derived_hex = parts
            iterations = 100_000
        else:
            return False
        
        derived = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), iterations)
        return secrets.compare_digest(derived.hex(), derived_hex)
    except Exception:
        return False

def generate_session_token() -> str:
    return secrets.token_urlsafe(32)
