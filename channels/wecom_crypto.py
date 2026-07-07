"""企业微信回调加解密(WXBizMsgCrypt 兼容子集)。"""
from __future__ import annotations

import base64
import hashlib
import struct
import xml.etree.ElementTree as ET

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def _sha1_sign(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    parts = sorted([token or "", timestamp or "", nonce or "", encrypt or ""])
    return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()


def _aes_key(encoding_aes_key: str) -> bytes:
    raw = (encoding_aes_key or "").strip()
    if len(raw) != 43:
        raise ValueError("EncodingAESKey 长度应为 43")
    return base64.b64decode(raw + "=")


def _pkcs7_unpad(data: bytes) -> bytes:
    pad = data[-1]
    if pad < 1 or pad > 32:
        raise ValueError("invalid pkcs7 padding")
    return data[:-pad]


def _pkcs7_pad(data: bytes) -> bytes:
    pad = 32 - (len(data) % 32)
    return data + bytes([pad]) * pad


def _decrypt(aes_key: bytes, encrypted_b64: str) -> str:
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(aes_key[:16]))
    decryptor = cipher.decryptor()
    plain = decryptor.update(base64.b64decode(encrypted_b64)) + decryptor.finalize()
    plain = _pkcs7_unpad(plain)
    msg_len = struct.unpack(">I", plain[16:20])[0]
    return plain[20 : 20 + msg_len].decode("utf-8")


def _encrypt(aes_key: bytes, text: str, receive_id: str) -> str:
    import os

    msg = (text or "").encode("utf-8")
    receive = (receive_id or "").encode("utf-8")
    blob = os.urandom(16) + struct.pack(">I", len(msg)) + msg + receive
    blob = _pkcs7_pad(blob)
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(aes_key[:16]))
    encryptor = cipher.encryptor()
    enc = encryptor.update(blob) + encryptor.finalize()
    return base64.b64encode(enc).decode("ascii")


class WeComCrypto:
    def __init__(self, token: str, encoding_aes_key: str, receive_id: str) -> None:
        self.token = (token or "").strip()
        self.receive_id = (receive_id or "").strip()
        self._aes_key = _aes_key(encoding_aes_key)

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
        enc = (echostr or "").strip()
        if _sha1_sign(self.token, timestamp, nonce, enc) != (msg_signature or "").strip():
            raise ValueError("msg_signature mismatch")
        return _decrypt(self._aes_key, enc)

    def decrypt_post(self, msg_signature: str, timestamp: str, nonce: str, post_body: bytes) -> str:
        root = ET.fromstring(post_body)
        enc_node = root.find("Encrypt")
        if enc_node is None or not (enc_node.text or "").strip():
            raise ValueError("missing Encrypt")
        enc = enc_node.text.strip()
        if _sha1_sign(self.token, timestamp, nonce, enc) != (msg_signature or "").strip():
            raise ValueError("msg_signature mismatch")
        return _decrypt(self._aes_key, enc)

    def encrypt_reply(self, plain_xml: str, timestamp: str, nonce: str) -> str:
        enc = _encrypt(self._aes_key, plain_xml, self.receive_id)
        sig = _sha1_sign(self.token, timestamp, nonce, enc)
        return (
            "<xml>"
            f"<Encrypt><![CDATA[{enc}]]></Encrypt>"
            f"<MsgSignature><![CDATA[{sig}]]></MsgSignature>"
            f"<TimeStamp>{timestamp}</TimeStamp>"
            f"<Nonce><![CDATA[{nonce}]]></Nonce>"
            "</xml>"
        )
