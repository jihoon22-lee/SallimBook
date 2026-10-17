"""Public wire-format bounds only; the API never receives a vault key or plaintext.

The client implementations and the shared crypto vectors own payload encoding,
AAD construction and encryption. These constants only constrain opaque storage.
"""

FORMAT_VERSION = 1
MAX_SAFE_INTEGER = 9_007_199_254_740_991
NONCE_BYTES = 12
SALT_BYTES = 16
WRAPPED_HVK_BYTES = 48
CARD_CIPHERTEXT_BYTES = 43
KEY_CHECK_PUBLIC_TEXT = b"SallimBook vault key check v1"
KEY_CHECK_CIPHERTEXT_BYTES = len(KEY_CHECK_PUBLIC_TEXT) + 16
MIN_PBKDF2_ITERATIONS = 600_000
MAX_PBKDF2_ITERATIONS = 2_000_000
