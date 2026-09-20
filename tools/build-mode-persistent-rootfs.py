#!/usr/bin/env python3
"""Build a device-specific EX520v rootfs that restores root only in Agent/AP mode."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


EXPECTED_ROOTFS_SHA256 = "1965299e5b41f656e83c6700283aeb1cda4ac246786cdb1f1db698938358d199"
MAX_ROOTFS_SIZE = 24 * 1024 * 1024
ASSETS = {
    "persistent-local-root.sh": 0o700,
    "ex520-root-api": 0o700,
    "ex520-dropbear": 0o700,
    "ex520-web-root-init": 0o700,
    "root-authorized-keys": 0o600,
    "root-api.token": 0o600,
    "release.version": 0o600,
    "config-key.hex": 0o600,
    "config-iv.hex": 0o600,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock-rootfs", required=True, type=Path)
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--boot-script", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--trial-return-to-ubi0",
        action="store_true",
        help="set the next boot back to the stock ubi0 bank during this boot",
    )
    args = parser.parse_args()

    stock = args.stock_rootfs.resolve(strict=True)
    assets = args.assets.resolve(strict=True)
    boot_script = args.boot_script.resolve(strict=True)
    output = args.output.resolve()

    actual = sha256(stock)
    if actual != EXPECTED_ROOTFS_SHA256:
        raise SystemExit(f"stock rootfs hash mismatch: {actual}")
    if output.exists():
        raise SystemExit(f"output already exists: {output}")

    for name in ASSETS:
        path = assets / name
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"missing asset: {path}")

    with tempfile.TemporaryDirectory(prefix="ex520-mode-rootfs-") as temporary:
        root = Path(temporary) / "rootfs"
        run("unsquashfs", "-no-progress", "-d", str(root), str(stock))

        destination = root / "usr/lib/ex520-mode-root"
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(boot_script, destination / "restore.sh")
        os.chmod(destination / "restore.sh", 0o700)
        for name, mode in ASSETS.items():
            shutil.copy2(assets / name, destination / name)
            os.chmod(destination / name, mode)

        rcs = root / "etc/init.d/rcS"
        text = rcs.read_text(encoding="utf-8")
        restore = "/usr/lib/ex520-mode-root/restore.sh &"
        trial_return = "/usr/bin/fw_setenv tp_boot_idx 0"
        if (
            restore in text
            or trial_return in text
            or text.count("\ncos &\n") != 1
        ):
            raise SystemExit("unexpected rcS layout")
        inserted = restore
        if args.trial_return_to_ubi0:
            inserted = f"{trial_return}\n{inserted}"
        text = text.replace("\ncos &\n", f"\ncos &\n{inserted}\n", 1)
        rcs.write_text(text, encoding="utf-8")

        run(
            "mksquashfs", str(root), str(output), "-noappend", "-comp", "xz",
            "-b", "262144", "-all-root", "-no-progress",
        )

    if output.stat().st_size > MAX_ROOTFS_SIZE:
        output.unlink()
        raise SystemExit("rebuilt rootfs exceeds the guarded 24 MiB limit")
    os.chmod(output, 0o600)
    print(f"output={output}")
    print(f"size={output.stat().st_size}")
    print(f"sha256={sha256(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
