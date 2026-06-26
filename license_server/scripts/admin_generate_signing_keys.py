from __future__ import annotations

import base64
from nacl.signing import SigningKey


def main():
    sk = SigningKey.generate()
    seed = sk._seed  # 32 bytes
    pk = sk.verify_key.encode()  # 32 bytes

    print("ED25519_SEED_HEX =", seed.hex())
    print("ED25519_PUB_HEX  =", pk.hex())
    print("ED25519_SEED_B64 =", base64.b64encode(seed).decode("ascii"))
    print("ED25519_PUB_B64  =", base64.b64encode(pk).decode("ascii"))


if __name__ == "__main__":
    main()
