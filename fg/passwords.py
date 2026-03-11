import hashlib
import hmac
import secrets

MURMUR_PBKDF2_SHA384 = 'murmur-pbkdf2-sha384'
MURMUR_LEGACY_SHA1 = 'murmur-sha1'
LEGACY_BCRYPT_SHA256 = 'bcrypt-sha256'

MURMUR_DERIVED_KEY_LENGTH = 48
MURMUR_SALT_BYTES = 8
MURMUR_MIN_KDF_ITERATIONS = 1000


def generate_murmur_salt():
    return secrets.token_hex(MURMUR_SALT_BYTES)


def hash_murmur_password(password, salt, kdf_iterations):
    derived = hashlib.pbkdf2_hmac(
        'sha384',
        password.encode('utf-8'),
        bytes.fromhex(salt),
        int(kdf_iterations),
        dklen=MURMUR_DERIVED_KEY_LENGTH,
    )
    return derived.hex()


def hash_legacy_murmur_password(password):
    return hashlib.sha1(password.encode('utf-8')).hexdigest()


def build_murmur_password_record(password, kdf_iterations=MURMUR_MIN_KDF_ITERATIONS):
    salt = generate_murmur_salt()
    return {
        'hashfn': MURMUR_PBKDF2_SHA384,
        'pwhash': hash_murmur_password(password, salt, kdf_iterations),
        'pw_salt': salt,
        'kdf_iterations': int(kdf_iterations),
    }


def verify_murmur_password(password, *, pwhash, hashfn, pw_salt='', kdf_iterations=None):
    if not pwhash:
        return False
    if hashfn == MURMUR_PBKDF2_SHA384:
        if not pw_salt or not kdf_iterations:
            return False
        candidate = hash_murmur_password(password, pw_salt, kdf_iterations)
        return hmac.compare_digest(candidate, pwhash)
    if hashfn == MURMUR_LEGACY_SHA1:
        candidate = hash_legacy_murmur_password(password)
        return hmac.compare_digest(candidate, pwhash)
    return False
