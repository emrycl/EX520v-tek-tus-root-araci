#!/usr/bin/env python3
"""Pack verified stock boot components and a guarded rootfs into an EX520v UBI."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path


EXPECTED = {
    "uboot": (662376, "6e4c0a032ccf24f212f028bb8df6d46717e64c032c6eccb165a01cecaceea329"),
    "kernel": (4056028, "f97c31dfe66fceb97f22f4ffb842d10892d1b930b97a759424ada6e952d24217"),
}
MAX_IMAGE_SIZE = 40 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_stock(name: str, path: Path) -> None:
    expected_size, expected_hash = EXPECTED[name]
    if path.stat().st_size != expected_size or sha256(path) != expected_hash:
        raise SystemExit(f"unexpected stock {name} image")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uboot", required=True, type=Path)
    parser.add_argument("--kernel", required=True, type=Path)
    parser.add_argument("--rootfs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    uboot = args.uboot.resolve(strict=True)
    kernel = args.kernel.resolve(strict=True)
    rootfs = args.rootfs.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"output already exists: {output}")
    verify_stock("uboot", uboot)
    verify_stock("kernel", kernel)
    if rootfs.stat().st_size > 24 * 1024 * 1024:
        raise SystemExit("rootfs exceeds guarded size")

    config = configparser.ConfigParser()
    for volume_id, (section, image) in enumerate(
        (("uboot", uboot), ("kernel", kernel), ("rootfs", rootfs))
    ):
        config[section] = {
            "mode": "ubi",
            "image": str(image),
            "vol_id": str(volume_id),
            "vol_type": "static",
            "vol_name": section,
            "vol_alignment": "1",
            "vol_size": str(image.stat().st_size),
        }

    with tempfile.NamedTemporaryFile("w", prefix="ex520-ubinize-", suffix=".ini") as ini:
        config.write(ini)
        ini.flush()
        subprocess.run(
            (
                "/usr/sbin/ubinize", "-o", str(output), "-m", "4096",
                "-p", "262144", "-s", "4096", ini.name,
            ),
            check=True,
        )

    if output.stat().st_size > MAX_IMAGE_SIZE:
        output.unlink()
        raise SystemExit("UBI image exceeds inactive bank size")
    os.chmod(output, 0o600)
    print(f"output={output}")
    print(f"size={output.stat().st_size}")
    print(f"sha256={sha256(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
