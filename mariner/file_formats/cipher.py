"""The two primitives the encrypted CTB format needs besides AES."""

import hashlib


def computeSHA256Hash(input: bytes) -> bytes:
    output = hashlib.sha256()
    output.update(input)
    return output.digest()


# https://github.com/sn4k3/UVtools/blob/2625c13cc3179a55865e5594180050258ab60a95/UVtools.Core/Extensions/CryptExtensions.cs#L59


def xorCipher(text: bytes, key: bytes) -> bytearray:
    output = bytearray(len(text))
    for i in range(len(text)):
        output[i] = text[i] ^ key[i % len(key)]
    return output
