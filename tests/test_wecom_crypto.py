"""企业微信回调加解密回归。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from channels.wecom_crypto import WeComCrypto, _aes_key, _encrypt, _sha1_sign


def test_wecom_crypto_roundtrip():
    token = "QDG6eK"
    receive_id = "wx5823bf96d3bd56c7"
    encoding_aes_key = "d3CuJ8TtrY6oTtawxO94VqxBozORSucSe/p4KbeVTgk"
    aes = _aes_key(encoding_aes_key)
    plain = "hello captain"
    enc = _encrypt(aes, plain, receive_id)
    crypto = WeComCrypto(token, encoding_aes_key, receive_id)
    ts = "1409659589"
    nonce = "263014780"
    sig = _sha1_sign(token, ts, nonce, enc)
    body = f"<xml><Encrypt><![CDATA[{enc}]]></Encrypt></xml>".encode("utf-8")
    out = crypto.decrypt_post(sig, ts, nonce, body)
    assert out == plain


def test_wecom_verify_url():
    token = "QDG6eK"
    receive_id = "wx5823bf96d3bd56c7"
    encoding_aes_key = "d3CuJ8TtrY6oTtawxO94VqxBozORSucSe/p4KbeVTgk"
    crypto = WeComCrypto(token, encoding_aes_key, receive_id)
    aes = _aes_key(encoding_aes_key)
    echostr_plain = "success_echo"
    enc = _encrypt(aes, echostr_plain, receive_id)
    ts = "1409659589"
    nonce = "263014780"
    sig = _sha1_sign(token, ts, nonce, enc)
    assert crypto.verify_url(sig, ts, nonce, enc) == echostr_plain
