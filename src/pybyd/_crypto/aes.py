"""Standard AES-128-CBC encryption for BYD inner payloads.

Ports aesEncryptHex and aesDecryptUtf8 from client.js.
"""

from __future__ import annotations

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from pybyd.exceptions import BydCryptoError

_ZERO_IV = b"\x00" * 16


def aes_encrypt_hex(plaintext: str, key_hex: str) -> str:
    """AES-128-CBC encrypt with zero IV, returning uppercase hex.

    Parameters
    ----------
    plaintext : str
        UTF-8 string to encrypt.
    key_hex : str
        32-character hex key (16 bytes).

    Returns
    -------
    str
        Uppercase hex ciphertext.

    Raises
    ------
    BydCryptoError
        If encryption fails.
    """
    try:
        key = bytes.fromhex(key_hex)
        padder = padding.PKCS7(128).padder()
        padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()
        cipher = Cipher(algorithms.AES(key), modes.CBC(_ZERO_IV))
        encryptor = cipher.encryptor()
        ct = encryptor.update(padded) + encryptor.finalize()
        return ct.hex().upper()
    except Exception as exc:
        raise BydCryptoError(f"AES encryption failed: {exc}") from exc


def aes_decrypt_utf8(cipher_hex: str, key_hex: str) -> str:
    """AES-128-CBC decrypt from hex with zero IV, returning UTF-8 string.

    Parameters
    ----------
    cipher_hex : str
        Hex-encoded ciphertext.
    key_hex : str
        32-character hex key (16 bytes).

    Returns
    -------
    str
        Decrypted UTF-8 plaintext.

    Raises
    ------
    BydCryptoError
        If decryption fails.
    """
    try:
        key = bytes.fromhex(key_hex)
        ct = bytes.fromhex(cipher_hex)
        cipher = Cipher(algorithms.AES(key), modes.CBC(_ZERO_IV))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ct) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded) + unpadder.finalize()
        return plaintext.decode("utf-8")
    except BydCryptoError:
        raise
    except Exception as exc:
        raise BydCryptoError(f"AES decryption failed: {exc}") from exc
