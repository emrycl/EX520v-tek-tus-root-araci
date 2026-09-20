#!/usr/bin/env python3
"""EX520v kurulum aracı."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import select
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import websocket

ROOT = Path(__file__).resolve().parent
MODEM = os.environ.get("EX520_HOST", "192.168.1.1").strip()
BASE_STATE_DIR = Path.home() / ".local" / "state" / "ex520-root"
STATE_DIR = BASE_STATE_DIR
PASSWORD_FILE = STATE_DIR / "root-password"
API_TOKEN_FILE = STATE_DIR / "api-token"
SSH_PRIVATE_KEY_FILE = STATE_DIR / "ssh-id-rsa"
SSH_PUBLIC_KEY_FILE = STATE_DIR / "ssh-id-rsa.pub"
SSH_KNOWN_HOSTS_FILE = STATE_DIR / "known_hosts"
HOOK_TEMPLATE = ROOT / "persistent-local-root.sh"
CDP_ENDPOINTS = ("http://127.0.0.1:9223/json/list", "http://127.0.0.1:9344/json/list", "http://127.0.0.1:9333/json/list")
PORT = 18084
API_PORT = 18080
SSH_PORT = 2222
BUNDLE_STALL_TIMEOUT = 300
BUNDLE_TOTAL_TIMEOUT = 1800
BUNDLE_RETRY_INTERVAL = 20
BUNDLE_MAX_TRIGGER_ATTEMPTS = 12
FIREWALL_PROBE_TIMEOUT = 8
VERSION = "root-agent"
VISIBLE_CDP_PORT = 9344
VISIBLE_PROFILE = Path.home() / ".local" / "share" / "ex520-root" / "browser-profile"
PERSISTENT_HOOK_URL = "file:///var/run/misc/misc_rw/persistent-local-root.sh"
LIFEMOTE_BACKUP_NAME = "lifemote.before.json"
LOCAL_LIFEMOTE_BACKUP_FILE = STATE_DIR / LIFEMOTE_BACKUP_NAME

SUPPORTED_MODEL = "EX520v"
SUPPORTED_FIRMWARE = "EX520v_260514"
LEGACY_WEB_TARGETS = (
    "/web/main/operateMode.htm",
    "/web/main/manageCtrl.htm",
    "/web/main/easyLocalAccess.htm",
    "/web/main/smarthomeEE.htm",
    "/web/main/ddos.htm",
    "/web/main/applicationList.htm",
    "/web/main/portMirror.htm",
    "/web/frame/menu.htm",
    "/web/frame/top.htm",
    "/web/js",
    "/web/frame",
)
LEGACY_WEB_ASSETS = (
    "operateMode.root.htm", "manageCtrl.root.htm", "easyLocalAccess.root.htm",
    "smarthomeEE.root.htm", "ddos.root.htm", "applicationList.root.htm",
    "portMirror.root.htm", "menu.root.htm", "top.root.htm",
    "tpee-enable.sh", "tpee-disable.sh", "ex520-bind-mount",
    "oid_str.unlocked.js",
)


def _set_state_dir(path: Path) -> None:
    global STATE_DIR, PASSWORD_FILE, API_TOKEN_FILE
    global SSH_PRIVATE_KEY_FILE, SSH_PUBLIC_KEY_FILE, SSH_KNOWN_HOSTS_FILE
    global LOCAL_LIFEMOTE_BACKUP_FILE

    STATE_DIR = path
    PASSWORD_FILE = path / "root-password"
    API_TOKEN_FILE = path / "api-token"
    SSH_PRIVATE_KEY_FILE = path / "ssh-id-rsa"
    SSH_PUBLIC_KEY_FILE = path / "ssh-id-rsa.pub"
    SSH_KNOWN_HOSTS_FILE = path / "known_hosts"
    LOCAL_LIFEMOTE_BACKUP_FILE = path / LIFEMOTE_BACKUP_NAME


def device_network_id() -> str:
    """Aynı IP'yi kullanan modemleri LAN MAC adresiyle birbirinden ayır."""
    override = os.environ.get("EX520_DEVICE_ID", "").strip().lower()
    if override:
        if not re.fullmatch(r"[a-z0-9_.-]{3,64}", override):
            raise SystemExit("EX520_DEVICE_ID biçimi geçersiz.")
        return hashlib.sha256(override.encode()).hexdigest()[:16]

    ip_tool = shutil.which("ip")
    arp_tool = shutil.which("arp")
    if arp_tool is None and Path("/usr/sbin/arp").is_file():
        arp_tool = "/usr/sbin/arp"

    commands: list[tuple[str, ...]] = []
    if ip_tool:
        commands.append((ip_tool, "neigh", "show", MODEM))
    if arp_tool:
        commands.extend((
            (arp_tool, "-n", MODEM),
            (arp_tool, "-an", MODEM),
            (arp_tool, "-a"),
        ))

    mac_pattern = re.compile(
        r"(?i)(?<![0-9a-f])(?:[0-9a-f]{1,2}[:-]){5}[0-9a-f]{1,2}"
        r"(?![0-9a-f])"
    )
    target_pattern = re.compile(
        rf"(?<![0-9.]){re.escape(MODEM)}(?![0-9.])"
    )

    for _ in range(3):
        try:
            with socket.create_connection((MODEM, 80), timeout=3):
                pass
        except OSError:
            pass

        for command in commands:
            try:
                result = subprocess.run(
                    command, check=False, capture_output=True, text=True,
                    timeout=5,
                )
            except (OSError, subprocess.SubprocessError):
                continue

            for line in result.stdout.splitlines():
                if not target_pattern.search(line):
                    continue
                match = mac_pattern.search(line)
                if not match:
                    continue
                normalized = re.sub(r"[:-]", "", match.group(0).lower())
                return hashlib.sha256(normalized.encode()).hexdigest()[:16]

        time.sleep(0.25)

    raise SystemExit(
        "Cihaz LAN kimliği belirlenemedi. Modeme bağlı olduğunuzu kontrol edip "
        "yeniden çalıştırın."
    )


def configure_device_state() -> None:
    """Kimlik bilgilerini kullanıcı müdahalesi olmadan cihaz bazında seç."""
    device_id = device_network_id()
    selected = BASE_STATE_DIR / "devices" / device_id
    marker = BASE_STATE_DIR / ".legacy-migrated"
    legacy_names = (
        "root-password", "api-token", "ssh-id-rsa", "ssh-id-rsa.pub",
        "known_hosts", LIFEMOTE_BACKUP_NAME,
    )

    selected.mkdir(mode=0o700, parents=True, exist_ok=True)
    selected.chmod(0o700)
    if not marker.exists():
        for name in legacy_names:
            source = BASE_STATE_DIR / name
            target = selected / name
            if source.is_file() and not target.exists():
                shutil.copy2(source, target)
                target.chmod(0o600)
        write_private(marker, device_id)

    _set_state_dir(selected)


@dataclass(frozen=True)
class Bundle:
    assets: dict[str, bytes]
    shell_password: str
    api_token: str
    nonce: str


def local_ip() -> str:
    """Modeme giden yerel IPv4 adresini bul."""
    override = os.environ.get("EX520_BIND", "").strip()
    if override:
        try:
            socket.inet_aton(override)
        except OSError as exc:
            raise SystemExit(f"EX520_BIND geçerli bir IPv4 adresi değil: {override}") from exc
        return override

    try:
        route = subprocess.run(
            ["ip", "route", "get", MODEM],
            check=True, capture_output=True, text=True, timeout=3,
        ).stdout
        match = re.search(r"(?:^|\s)src\s+(\d+\.\d+\.\d+\.\d+)(?:\s|$)", route)
        if match:
            return match.group(1)
    except (OSError, subprocess.SubprocessError):
        pass

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((MODEM, 80))
        address = str(sock.getsockname()[0])
    return address


FirewallRule = tuple[tuple[str, ...], tuple[str, ...]]


def open_temporary_firewall(bind: str) -> FirewallRule | None:
    """Modem aktarımı için geçici yerel firewall izni ekle."""
    if os.name == "nt":
        name = "EX520 Root temporary transfer"
        add = (
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
            "$p=Start-Process netsh -Verb RunAs -Wait -PassThru -ArgumentList "
            f"'advfirewall','firewall','add','rule','name={name}','dir=in',"
            f"'action=allow','protocol=TCP','localport={PORT}','remoteip={MODEM}'; "
            "exit $p.ExitCode",
        )
        remove = (
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
            "$p=Start-Process netsh -Verb RunAs -Wait -PassThru -ArgumentList "
            f"'advfirewall','firewall','delete','rule','name={name}'; "
            "exit $p.ExitCode",
        )
        result = subprocess.run(add, check=False)
        return (add, remove) if result.returncode == 0 else None

    if sys.platform == "darwin":
        firewall = Path("/usr/libexec/ApplicationFirewall/socketfilterfw")
        sudo = shutil.which("sudo")
        if not firewall.is_file() or not sudo:
            return None
        python = str(Path(sys.executable).resolve())
        add = (sudo, str(firewall), "--add", python)
        unblock = (sudo, str(firewall), "--unblockapp", python)
        remove = (sudo, "-n", str(firewall), "--remove", python)
        if subprocess.run(add, check=False).returncode != 0:
            return None
        if subprocess.run(unblock, check=False).returncode != 0:
            subprocess.run(remove, check=False)
            return None
        return (add, remove)

    if not sys.platform.startswith("linux"):
        return None

    iptables = shutil.which("iptables")
    if iptables is None:
        for candidate in ("/usr/sbin/iptables", "/sbin/iptables"):
            if Path(candidate).is_file():
                iptables = candidate
                break
    sudo = shutil.which("sudo")
    if not iptables or not sudo:
        return None

    rule = (
        "INPUT", "-s", MODEM, "-d", bind, "-p", "tcp",
        "--dport", str(PORT), "-j", "ACCEPT",
    )
    print(
        "[GÜVENLİK DUVARI] Modem aktarımı için geçici yerel izin gerekiyor.",
        flush=True,
    )
    result = subprocess.run(
        (sudo, iptables, "-I", *rule),
        check=False,
    )
    if result.returncode != 0:
        return None
    return ((sudo, iptables, "-I", *rule), (sudo, "-n", iptables, "-D", *rule))


def close_temporary_firewall(rule: FirewallRule | None) -> None:
    if rule is None:
        return
    _, remove = rule
    result = subprocess.run(
        remove,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode == 0:
        print("[GÜVENLİK DUVARI] Geçici yerel izin kaldırıldı.", flush=True)
    else:
        print(
            "[UYARI] Geçici güvenlik duvarı kuralı otomatik kaldırılamadı.",
            flush=True,
        )


def write_private(path: Path, value: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(value + "\n")


def shell_password() -> str:
    if not PASSWORD_FILE.exists():
        write_private(PASSWORD_FILE, secrets.token_urlsafe(27))
    PASSWORD_FILE.chmod(0o600)
    value = PASSWORD_FILE.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{24,80}", value):
        raise SystemExit("Üretilen root parola dosyasının biçimi geçersiz.")
    return value


def existing_shell_password() -> str:
    if not PASSWORD_FILE.is_file():
        raise SystemExit(
            f"Root parola dosyası bulunamadı: {PASSWORD_FILE}"
        )
    PASSWORD_FILE.chmod(0o600)
    value = PASSWORD_FILE.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{24,80}", value):
        raise SystemExit("Kayıtlı root parola dosyasının biçimi geçersiz.")
    return value


def api_token() -> str:
    # Yarım kalan kurulumlarda token önceden oluşturulmuş olabilir.
    if not API_TOKEN_FILE.exists():
        write_private(API_TOKEN_FILE, secrets.token_hex(24))
    API_TOKEN_FILE.chmod(0o600)
    value = API_TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9a-f]{48}", value):
        raise SystemExit("Kayıtlı API token dosyasının biçimi geçersiz.")
    return value


def ssh_public_key() -> bytes:
    """SSH anahtarını hazırla ve açık anahtarı döndür."""
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    STATE_DIR.chmod(0o700)
    if not SSH_PRIVATE_KEY_FILE.is_file() or not SSH_PUBLIC_KEY_FILE.is_file():
        for path in (SSH_PRIVATE_KEY_FILE, SSH_PUBLIC_KEY_FILE):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        try:
            subprocess.run(
                [
                    "ssh-keygen", "-q", "-t", "rsa", "-b", "2048", "-N", "",
                    "-C", "ex520-root", "-f", str(SSH_PRIVATE_KEY_FILE),
                ],
                check=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SystemExit("SSH anahtarı üretilemedi; OpenSSH araçları gerekli.") from exc
    SSH_PRIVATE_KEY_FILE.chmod(0o600)
    SSH_PUBLIC_KEY_FILE.chmod(0o600)
    public_key = SSH_PUBLIC_KEY_FILE.read_bytes()
    if not re.fullmatch(
        rb"ssh-rsa [A-Za-z0-9+/=]+ ex520-root(?:\r?\n)?",
        public_key,
    ):
        raise SystemExit("Üretilen SSH açık anahtarının biçimi geçersiz.")
    return public_key.rstrip(b"\r\n") + b"\n"


def refresh_ssh_known_host() -> None:
    """Doğrulanan kurulumun SSH sunucu anahtarını cihaz kaydına yaz."""
    try:
        result = subprocess.run(
            ("ssh-keyscan", "-T", "5", "-p", str(SSH_PORT), MODEM),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SystemExit("SSH sunucu anahtarı okunamadı.") from exc

    prefix = f"[{MODEM}]:{SSH_PORT} "
    keys = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.startswith(prefix)
        and re.fullmatch(
            rf"\[{re.escape(MODEM)}\]:{SSH_PORT} "
            r"(?:ssh-rsa|ssh-ed25519|ecdsa-sha2-nistp(?:256|384|521)) "
            r"[A-Za-z0-9+/=]+",
            line.strip(),
        )
    ]
    if result.returncode != 0 or not keys:
        raise SystemExit("SSH sunucu anahtarı doğrulanabilir biçimde alınamadı.")

    write_private(SSH_KNOWN_HOSTS_FILE, "\n".join(keys))


def required(path: Path) -> bytes:
    if not path.is_file():
        raise SystemExit(f"Gerekli paket dosyası eksik: {path.relative_to(ROOT)}")
    return path.read_bytes()


def disable_legacy_watcher() -> None:
    """Eski Linux kullanıcı servisini yalnızca mevcutsa kapat."""
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return
    subprocess.run(
        [systemctl, "--user", "disable", "--now", "ex520-web-root-watch.service"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def build_bundle(
    bind: str,
    lifemote_backup: bytes | None = None,
) -> Bundle:
    password = shell_password()
    token = api_token()
    nonce = secrets.token_urlsafe(24)

    if lifemote_backup is None:
        lifemote_backup = lifemote_backup_bytes(
            None,
            known=False,
        )
    try:
        backup_is_known = json.loads(lifemote_backup.decode()).get("known") is True
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        raise SystemExit("Üretilen Lifemote yedeği geçersiz.")

    hook = required(HOOK_TEMPLATE).decode()
    if hook.count("__ROOT_PASSWORD__") != 1 or hook.count("__PANEL_ROOT_PASSWORD__") != 1:
        raise SystemExit("Root parola yer tutucusunun sayısı geçersiz.")
    hook = hook.replace("__ROOT_PASSWORD__", password)
    hook = hook.replace("__PANEL_ROOT_PASSWORD__", password[:32])
    assets = {
        "persistent-local-root.sh": hook.encode(),
        "ex520-root-api": required(ROOT / "tools/ex520-root-api"),
        "ex520-dropbear": required(ROOT / "tools/ex520-dropbear"),
        "ex520-web-root-init": required(ROOT / "tools/ex520-web-root-init"),
        "root-authorized-keys": ssh_public_key(),
        "root-api.token": (token + "\n").encode(),
        "release.version": (VERSION + "\n").encode(),
        LIFEMOTE_BACKUP_NAME: lifemote_backup,
        "install-complete": b"OK\n",
    }
    unmounts = "\n".join(
        f"while /bin/umount {target} 2>/dev/null; do :; done"
        for target in LEGACY_WEB_TARGETS
    )
    installed_names = [
        "persistent-local-root.sh", "ex520-root-api", "ex520-web-root-init",
        "ex520-dropbear", "ex520-dropbear-rsa-host-key", "root-authorized-keys",
        "root-api.token", "release.version",
        LIFEMOTE_BACKUP_NAME, "rollback.sh",
        *LEGACY_WEB_ASSETS,
    ]
    remove_assets = " ".join(f'"$dst/{name}"' for name in installed_names)
    remove_temp_assets = " ".join(f'"$dst/{name}.new"' for name in installed_names)
    assets["rollback.sh"] = f"""#!/bin/sh
set -eu
dst=/var/run/misc/misc_rw
cfg=/var/tmp/container/app_Wifispot/Wifispot/config

# Önce dinleyicileri çalıştıran süreç durdurulur.
if [ -s /var/run/persistent-local-root.pid ]; then
    /bin/kill "$(/bin/cat /var/run/persistent-local-root.pid)" \
        2>/dev/null || true
fi
/bin/rm -f /var/run/persistent-local-root.pid
/bin/sleep 1

# Konteyner ayarını geri yükle.
if [ -f "$cfg.pre-root-hook" ]; then
    /bin/cp -p "$cfg.pre-root-hook" "$cfg"
    /bin/rm -f "$cfg.pre-root-hook"
else
    /bin/sed -i '\\|persistent-local-root.sh|d' "$cfg"
fi

# Web bağlarını kaldır.
{unmounts}
/bin/rm -rf /var/tmp/ex520-web-js /var/tmp/ex520-web-frame

/usr/bin/killall ex520-root-api >/dev/null 2>&1 || true

# SSH'yi durdur ve root ev dizinini geri yükle.
if [ -s /var/run/ex520-dropbear.pid ]; then
    /bin/kill "$(/bin/cat /var/run/ex520-dropbear.pid)" 2>/dev/null || true
fi
/bin/rm -f /var/run/ex520-dropbear.pid
if [ -f /var/passwd ]; then
    /bin/sed -i 's|^\\(root:[^:]*:0:0:[^:]*:\\)[^:]*:\\(.*\\)$|\\1/:\\2|' /var/passwd
fi
/bin/rm -f /var/run/misc/misc_rw/root-home/.ssh/authorized_keys
/bin/rmdir /var/run/misc/misc_rw/root-home/.ssh 2>/dev/null || true
/bin/rmdir /var/run/misc/misc_rw/root-home 2>/dev/null || true

# Durdurulmuş stok servisleri devam ettir.
 /usr/bin/killall -CONT cwmp >/dev/null 2>&1 || true
 /usr/bin/killall -CONT obuspa >/dev/null 2>&1 || true

for proc in /proc/[0-9]*; do
    [ -r "$proc/cmdline" ] || continue

    if /bin/grep -aq '/etc/quantWiFiLoader.sh' "$proc/cmdline"; then
        pid="${{proc#/proc/}}"
        /bin/kill -CONT "$pid" >/dev/null 2>&1 || true
    fi
done

/bin/rm -f \
    /var/tmp/persistent-root-login.sh \
    /var/tmp/ex520-root-api.log

# Lifemote bu betik çalışmadan önce geri yüklenir.
/bin/rm -f {remove_assets}
/bin/rm -f {remove_temp_assets}

echo ROLLBACK_REBOOT_REQUIRED
echo ROLLBACK_OK

# İstemcinin sonucu almasına zaman tanı.
(
    /bin/sleep 1

    for proc in /proc/[0-9]*; do
        [ -r "$proc/cmdline" ] || continue

        if /bin/grep -aq 'telnetd' "$proc/cmdline" && \
           /bin/grep -aq '2323' "$proc/cmdline" && \
           /bin/grep -aq 'persistent-root-login.sh' "$proc/cmdline"; then
            pid="${{proc#/proc/}}"
            /bin/kill "$pid" >/dev/null 2>&1 || true
        fi
    done
) >/dev/null 2>&1 &
""".encode()

    base = f"http://{bind}:{PORT}/{nonce}"
    transfers = [
        ("persistent-local-root.sh", "persistent-local-root.sh", "700"),
        ("ex520-root-api", "ex520-root-api", "700"),
        ("ex520-web-root-init", "ex520-web-root-init", "700"),
        ("ex520-dropbear", "ex520-dropbear", "700"),
        ("root-authorized-keys", "root-authorized-keys", "600"),
        ("root-api.token", "root-api.token", "600"),
        ("release.version", "release.version", "600"),
        (LIFEMOTE_BACKUP_NAME, LIFEMOTE_BACKUP_NAME, "600"),
        ("rollback.sh", "rollback.sh", "700"),
    ]
    # misc_rw sınırlı olduğu için büyük dosyaları önce aktar.
    transfers.sort(
        key=lambda item: len(assets[item[0]]),
        reverse=True,
    )

    installs = [
        (
            f"install_one {remote} {local} {mode} "
            f"{hashlib.sha256(assets[remote]).hexdigest()}"
        )
        for remote, local, mode in transfers
    ]
    cleanup_temps = [f'/bin/rm -f "$dst/{local}.new"' for _, local, _ in transfers]
    unmounts = [f"while /bin/umount {target} 2>/dev/null; do :; done" for target in LEGACY_WEB_TARGETS]
    legacy_cleanup = [f'/bin/rm -f "$dst/{name}"' for name in LEGACY_WEB_ASSETS]
    installer = f"""#!/bin/sh
set -eu
base='{base}'
dst=/var/run/misc/misc_rw

# Yarım kalan aktarımların geçici dosyalarını temizle.
{chr(10).join(cleanup_temps)}

install_one() {{
    remote="$1"; local="$2"; mode="$3"; expected_sha="$4"
    current="$dst/$local"
    tmp="$current.new"

    if [ "$remote" = "lifemote.before.json" ] && [ -f "$current" ] && \
       [ "{0 if backup_is_known else 1}" = "1" ]; then
        /bin/chmod 600 "$current"

        if /usr/bin/wget -O /dev/null "$base/$remote"; then
            echo "PRESERVE_OK:$remote"
            return 0
        fi

        echo "PRESERVE_NOTIFY_FAILED:$remote" >&2
        return 1
    fi

    if [ ! -x /usr/sbin/openssl ]; then
        echo "OPENSSL_SHA256_UNAVAILABLE:$remote" >&2
        return 1
    fi

    # Aynı dosyayı yeniden yazma.
    if [ -f "$current" ]; then
        current_sha="$(/usr/sbin/openssl dgst -sha256 "$current" 2>/dev/null | /usr/bin/awk '{{print $NF}}')" || current_sha=""

        if [ "$current_sha" = "$expected_sha" ]; then
            /bin/chmod "$mode" "$current"

            echo "SKIP_OK:$remote"
            return 0
        fi
    fi

    attempt=1
    while [ "$attempt" -le 3 ]; do
        /bin/rm -f "$tmp"

        if /usr/bin/wget -O "$tmp" "$base/$remote"; then
            downloaded_sha="$(/usr/sbin/openssl dgst -sha256 "$tmp" 2>/dev/null | /usr/bin/awk '{{print $NF}}')" || downloaded_sha=""

            if [ "$downloaded_sha" = "$expected_sha" ]; then
                /bin/chmod "$mode" "$tmp"
                /bin/mv "$tmp" "$current"
                return 0
            fi

            echo "HASH_MISMATCH:$remote:got=$downloaded_sha:expected=$expected_sha" >&2
        fi

        /bin/rm -f "$tmp"
        attempt=$((attempt + 1))
        /bin/sleep 1
    done

    echo "FETCH_FAILED:$remote" >&2
    return 1
}}
{chr(10).join(installs)}
{chr(10).join(unmounts)}
{chr(10).join(legacy_cleanup)}
cfg=/var/tmp/container/app_Wifispot/Wifispot/config
hook="$dst/persistent-local-root.sh"
if [ -f "$cfg" ] && ! /bin/grep -q 'persistent-local-root.sh' "$cfg"; then
    /bin/cp -p "$cfg" "$cfg.pre-root-hook"
    echo 'lxc.hook.pre-start = /var/run/misc/misc_rw/persistent-local-root.sh' >> "$cfg"
fi
/usr/bin/killall ex520-root-api >/dev/null 2>&1 || true
/bin/kill "$(/bin/cat /var/run/persistent-local-root.pid 2>/dev/null)" >/dev/null 2>&1 || true
/bin/rm -f /var/run/persistent-local-root.pid
/bin/sh "$hook"

# Kurulumun tamamlandığını istemciye bildir.
/usr/bin/wget -O /dev/null "$base/install-complete"
""".encode()
    assets["install.sh"] = installer
    return Bundle(assets, password, token, nonce)


def upgrade_over_existing_ssh(bundle: Bundle) -> bool:
    """Mevcut UID 0 SSH kurulumu üzerinden paketi atomik olarak yenile."""
    if not ssh_ready(timeout=5):
        return False

    modes = {
        "persistent-local-root.sh": "700",
        "ex520-root-api": "700",
        "ex520-dropbear": "700",
        "ex520-web-root-init": "700",
        "root-authorized-keys": "600",
        "root-api.token": "600",
        "release.version": "600",
        LIFEMOTE_BACKUP_NAME: "600",
        "rollback.sh": "700",
    }
    ssh_base = [
        "ssh", "-i", str(SSH_PRIVATE_KEY_FILE), "-p", str(SSH_PORT),
        "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
        "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
        "-o", f"UserKnownHostsFile={os.devnull}", f"root@{MODEM}",
    ]

    for name, mode in modes.items():
        payload = bundle.assets[name]
        expected = hashlib.sha256(payload).hexdigest()
        target = f"/var/run/misc/misc_rw/{name}"
        current_hash = subprocess.run(
            [
                *ssh_base,
                f"/usr/sbin/openssl dgst -sha256 -r '{target}' 2>/dev/null | "
                "/usr/bin/awk '{print $1}'",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if current_hash.returncode == 0 and current_hash.stdout.strip() == expected:
            continue
        command = (
            "set -eu; umask 077; "
            f"/bin/dd of='{target}.new' bs=4096 2>/dev/null; "
            f"got=$(/usr/sbin/openssl dgst -sha256 '{target}.new' | /usr/bin/awk '{{print $NF}}'); "
            f"[ \"$got\" = '{expected}' ]; /bin/chmod {mode} '{target}.new'; "
            f"/bin/mv '{target}.new' '{target}'"
        )
        try:
            result = subprocess.run(
                [*ssh_base, command], input=payload, check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            print(f"[HATA] SSH aktarımı tamamlanamadı: {name}", flush=True)
            return False
        if result.returncode != 0:
            print(f"[HATA] SSH bütünlük doğrulaması başarısız: {name}", flush=True)
            return False

    activate = """set -eu
/usr/bin/killall ex520-root-api >/dev/null 2>&1 || true
if [ -s /var/run/persistent-local-root.pid ]; then
    /bin/kill "$(/bin/cat /var/run/persistent-local-root.pid)" 2>/dev/null || true
fi
/bin/rm -f /var/run/persistent-local-root.pid
/bin/sh /var/run/misc/misc_rw/persistent-local-root.sh
"""
    try:
        result = subprocess.run(
            [*ssh_base, activate], check=False, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


class PayloadServer(ThreadingHTTPServer):
    allow_reuse_address = True


def serve_bundle(bind: str, bundle: Bundle):
    complete = threading.Event()
    fetched: set[str] = set()
    lock = threading.Lock()
    expected = set(bundle.assets)

    def snapshot() -> tuple[list[str], list[str]]:
        with lock:
            return sorted(fetched), sorted(expected - fetched)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health":
                body = b"OK\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            request = urlsplit(self.path)
            prefix = f"/{bundle.nonce}/"
            name = request.path[len(prefix):] if request.path.startswith(prefix) else ""
            body = bundle.assets.get(name)
            if body is None or "/" in name:
                print(f"[HTTP] 404 {self.client_address[0]} GET {self.path}", flush=True)
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            response_body = b"" if request.query == "already-present=1" else body
            self.send_header("Content-Length", str(len(response_body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(response_body)

            with lock:
                first = name not in fetched
                fetched.add(name)
                if name == "install-complete":
                    complete.set()

            if first:
                print(f"[AKTARIM] {name}", flush=True)
                if name == "install-complete":
                    print("[AKTARIM] Bütün dosyalar modeme ulaştı.", flush=True)
                else:
                    print(
                        "[BEKLEME] Kurulum tamamlanma bildirimi bekleniyor.",
                        flush=True,
                    )

        def log_message(self, *_: object) -> None:
            return

    server = PayloadServer((bind, PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, complete, snapshot


def _panel_target_score(target: dict[str, object]) -> int:
    """Yeniden başlatma öncesinden kalan sekmeler yerine canlı paneli seç."""
    connection = websocket.create_connection(
        str(target["webSocketDebuggerUrl"]), timeout=3, suppress_origin=True
    )
    try:
        expression = r"""(() => {
          const visible = node => !!node && !!(node.offsetWidth || node.offsetHeight);
          return {
            backend: !!window.$?.dm,
            login: visible(document.querySelector('#pc-login-password')),
            passwordChange: visible(document.querySelector('#pc-setPwd-new')),
            complete: document.readyState === 'complete',
            titled: !!document.title
          };
        })()"""
        connection.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True},
        }))
        while True:
            message = json.loads(connection.recv())
            if message.get("id") != 1:
                continue
            state = message.get("result", {}).get("result", {}).get("value", {})
            if not isinstance(state, dict):
                return 0
            return (
                100 * bool(state.get("backend"))
                + 40 * bool(state.get("login"))
                + 20 * bool(state.get("passwordChange"))
                + 5 * bool(state.get("complete"))
                + bool(state.get("titled"))
            )
    finally:
        connection.close()


def panel_page() -> dict[str, object]:
    candidates: list[tuple[int, dict[str, object]]] = []
    for endpoint in CDP_ENDPOINTS:
        try:
            with urllib.request.urlopen(endpoint, timeout=2) as response:
                targets = json.load(response)
            for target in targets:
                if target.get("type") != "page":
                    continue
                parsed = urlsplit(str(target.get("url", "")))
                if parsed.scheme in {"http", "https"} and parsed.hostname == MODEM:
                    try:
                        candidates.append((_panel_target_score(target), target))
                    except (OSError, ValueError, websocket.WebSocketException):
                        continue
        except (OSError, ValueError):
            continue
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    raise SystemExit("Kontrollü Chrome içinde modem paneli bulunamadı.")


def evaluate(expression: str) -> object:
    target = panel_page()
    connection = websocket.create_connection(str(target["webSocketDebuggerUrl"]), timeout=15, suppress_origin=True)
    try:
        connection.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
            "expression": expression, "awaitPromise": True, "returnByValue": True,
        }}))
        while True:
            message = json.loads(connection.recv())
            if message.get("id") == 1:
                outer = message.get("result", {})
                if outer.get("exceptionDetails"):
                    raise RuntimeError("Tarayıcı değerlendirmesi başarısız.")
                return outer.get("result", {}).get("value")
    finally:
        connection.close()


def clear_panel_session() -> None:
    """Kontrollü tarayıcıdaki modem oturumunu temizle."""
    target = panel_page()
    connection = websocket.create_connection(
        str(target["webSocketDebuggerUrl"]), timeout=15, suppress_origin=True
    )
    try:
        for command_id, method, params in (
            (1, "Network.clearBrowserCookies", {}),
            (2, "Page.navigate", {"url": f"http://{MODEM}/"}),
        ):
            connection.send(json.dumps({
                "id": command_id,
                "method": method,
                "params": params,
            }))
            while True:
                message = json.loads(connection.recv())
                if message.get("id") == command_id:
                    if message.get("error"):
                        raise RuntimeError(f"CDP {method} failed")
                    break
    finally:
        connection.close()


def trigger(url: str) -> bool:
    expression = """new Promise(resolve => {
      if (!window.$?.dm) return resolve(false);
      $.dm.set({oid:'DEV2_LIFEMOTE_AGENT',data:{enable:1,URL:%s},callback:{
        success:()=>resolve(true),fail:()=>resolve(false),error:()=>resolve(false)}});
    })""" % json.dumps(url)
    return evaluate(expression) is True


def activate_lifemote(url: str) -> bool:
    """İndirme sürecini güvenilir biçimde yeniden başlat."""
    if not set_lifemote_state("0", ""):
        return False
    time.sleep(1)
    return trigger(url)


def activate_lifemote_with_fresh_login(url: str) -> bool:
    """Yazma yetkisi düşmüş panel oturumunu bir kez yenileyerek tekrar dene."""
    if activate_lifemote(url):
        return True

    print(
        "[GİRİŞ] Panel yazma oturumu yenileniyor.",
        flush=True,
    )
    clear_panel_session()
    if not try_default_panel_login():
        wait_for_panel_login()
    return activate_lifemote(url)


def lifemote_state() -> dict[str, str] | None:
    """Lifemote durumunu oku."""
    expression = r"""
new Promise(resolve => {
    if (!window.$?.dm) {
        return resolve(null);
    }

    $.dm.get({
        oid: 'DEV2_LIFEMOTE_AGENT',
        data: {
            enable: '',
            URL: ''
        },
        callback: {
            success: d => resolve({
                enable: String(d?.enable ?? ''),
                URL: String(d?.URL ?? '')
            }),
            fail: () => resolve(null),
            error: () => resolve(null)
        }
    });
})
"""

    value = evaluate(expression)

    if not isinstance(value, dict):
        return None

    return {
        "enable": str(value.get("enable", "")),
        "URL": str(value.get("URL", "")),
    }




def set_lifemote_state(enable: str, url: str) -> bool:
    """Kaydedilmiş Lifemote durumunu geri yükle."""
    enabled = 1 if str(enable).strip().lower() in {
        "1", "true", "yes", "on"
    } else 0

    expression = """new Promise(resolve => {
      if (!window.$?.dm) return resolve(false);
      $.dm.set({
        oid:'DEV2_LIFEMOTE_AGENT',
        data:{enable:%d,URL:%s},
        callback:{
          success:()=>resolve(true),
          fail:()=>resolve(false),
          error:()=>resolve(false)
        }
      });
    })""" % (enabled, json.dumps(str(url)))

    return evaluate(expression) is True


def lifemote_state_is_managed(state: dict[str, str] | None) -> bool:
    if not state:
        return False

    url = str(state.get("URL", "")).strip()

    if url == PERSISTENT_HOOK_URL:
        return True

    return (
        ":18084/" in url
        and url.endswith("/install.sh")
    )


def lifemote_backup_bytes(
    state: dict[str, str] | None,
    *,
    known: bool,
) -> bytes:
    payload = {
        "schema": 1,
        "known": bool(known and state is not None),
        "enable": (
            str(state.get("enable", ""))
            if state is not None
            else ""
        ),
        "URL": (
            str(state.get("URL", ""))
            if state is not None
            else ""
        ),
        "captured_by": VERSION,
    }

    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def known_local_lifemote_backup() -> bytes | None:
    try:
        raw = LOCAL_LIFEMOTE_BACKUP_FILE.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    if (
        not isinstance(payload, dict)
        or payload.get("schema") != 1
        or payload.get("known") is not True
        or not isinstance(payload.get("enable"), str)
        or not isinstance(payload.get("URL"), str)
    ):
        return None

    LOCAL_LIFEMOTE_BACKUP_FILE.chmod(0o600)
    return raw


def save_known_lifemote_backup(raw: bytes) -> None:
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("known") is not True:
        raise ValueError("doğrulanmamış Lifemote yedeği kaydedilemez")
    write_private(LOCAL_LIFEMOTE_BACKUP_FILE, raw.decode("utf-8").rstrip("\n"))



def device_fingerprint() -> dict[str, str]:
    """Model ve sürüm bilgilerini panelden oku."""
    expression = r"""
new Promise(resolve => {
    if (!window.$?.dm) {
        return resolve({ok:false, error:"no $.dm"});
    }

    $.dm.get({
        oid: 'DEV2_DEV_INFO',
        data: {
            modelName: '',
            hardwareVersion: '',
            softwareVersion: ''
        },
        callback: {
            success: d => resolve({
                ok: true,
                model: String(d.modelName || document.title || '').trim(),
                hardwareVersion: String(d.hardwareVersion || '').trim(),
                softwareVersion: String(d.softwareVersion || '').trim()
            }),
            fail: e => resolve({
                ok: false,
                error: "DEV2_DEV_INFO read failed",
                detail: String(e)
            }),
            error: e => resolve({
                ok: false,
                error: "DEV2_DEV_INFO error",
                detail: String(e)
            })
        }
    });
})
"""
    result = evaluate(expression)

    if not isinstance(result, dict) or result.get("ok") is not True:
        raise SystemExit(
            "Cihaz kontrolü başarısız: panel oturumu veya DEV2_DEV_INFO "
            "verisi kullanılamıyor."
        )

    hardware = str(result.get("hardwareVersion", "")).strip()
    firmware = str(result.get("softwareVersion", "")).strip()
    model = str(result.get("model", "")).strip()

    # DEV2_DEV_INFO hazır olduğunda sayfa başlığı henüz boş olabilir.
    if not model and re.search(r"(?i)EX520V", hardware):
        model = SUPPORTED_MODEL
    if re.search(r"(?i)(?:^|\b)EX520V(?:\b|_)", model):
        model = SUPPORTED_MODEL

    return {
        "model": model,
        "hardwareVersion": hardware,
        "softwareVersion": firmware,
    }


def enforce_supported_device() -> dict[str, str]:
    fp = device_fingerprint()

    print(
        "[KONTROL] "
        f"model={fp['model']!r} "
        f"donanım={fp['hardwareVersion']!r} "
        f"firmware={fp['softwareVersion']!r}",
        flush=True,
    )

    expected = {
        "model": SUPPORTED_MODEL,
        "softwareVersion": SUPPORTED_FIRMWARE,
    }

    mismatches = [
        f"{key}: bulunan {fp[key]!r}, beklenen {value!r}"
        for key, value in expected.items()
        if fp[key] != value
    ]

    if mismatches:
        raise SystemExit(
            "DESTEKLENMEYEN_CİHAZ: " + "; ".join(mismatches)
        )

    print(
        "[KONTROL] EX520v modeli ve desteklenen firmware doğrulandı; "
        "donanım revizyonu kısıtlanmıyor.",
        flush=True,
    )
    return fp

def root_ready(secret: str, timeout: int = 30) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        connection = None
        try:
            connection = _open_authenticated_root_shell(
                secret,
                timeout=min(8, max(2, deadline - time.monotonic())),
            )
            connection.settimeout(2)
            connection.sendall(b"cat /proc/self/status\nexit\n")
            output = bytearray()
            try:
                while chunk := connection.recv(4096):
                    output.extend(chunk)
            except socket.timeout:
                pass
            if re.search(
                br"(?:^|\r?\n)Uid:\s+0\s+0\s+0\s+0(?:\r?\n|$)",
                output,
            ):
                return True
        except (OSError, SystemExit):
            pass
        finally:
            if connection is not None:
                connection.close()
        time.sleep(1)
    return False



def remote_release_matches(
    secret: str,
    expected: str,
    timeout: int = 3,
) -> bool:
    """Modemdeki sürüm işaretini kontrol et."""
    end_marker = b"__EX520_RELEASE_END__"

    try:
        with socket.create_connection((MODEM, 2323), timeout=1) as connection:
            connection.setblocking(False)

            received = bytearray()
            deadline = time.monotonic() + timeout

            while b"username:" not in received and time.monotonic() < deadline:
                readable, _, _ = select.select(
                    [connection], [], [], 0.2
                )
                if readable:
                    chunk = connection.recv(4096)
                    if not chunk:
                        return False
                    received.extend(chunk)

            if b"username:" not in received:
                return False

            connection.sendall(b"root\n")
            received = bytearray()
            deadline = time.monotonic() + timeout

            while b"password:" not in received and time.monotonic() < deadline:
                readable, _, _ = select.select([connection], [], [], 0.2)
                if readable:
                    chunk = connection.recv(4096)
                    if not chunk:
                        return False
                    received.extend(chunk)

            if b"password:" not in received:
                return False

            connection.sendall((secret + "\n").encode())

            shell = bytearray()
            deadline = time.monotonic() + timeout

            while (
                not re.search(
                    br"(?:^|[\r\n])[^\r\n]*#\s*$",
                    shell,
                )
                and time.monotonic() < deadline
            ):
                readable, _, _ = select.select(
                    [connection], [], [], 0.2
                )
                if readable:
                    chunk = connection.recv(4096)
                    if not chunk:
                        return False
                    shell.extend(chunk)

            if not re.search(
                br"(?:^|[\r\n])[^\r\n]*#\s*$",
                shell,
            ):
                return False

            connection.sendall(
                b"cat /var/run/misc/misc_rw/release.version "
                b"2>/dev/null; "
                b"echo __EX520_RELEASE_END__; exit\n"
            )

            output = bytearray()
            deadline = time.monotonic() + timeout

            while (
                end_marker not in output
                and time.monotonic() < deadline
            ):
                readable, _, _ = select.select(
                    [connection], [], [], 0.2
                )
                if readable:
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    output.extend(chunk)

            if end_marker not in output:
                return False

            expected_bytes = expected.encode()

            return re.search(
                rb"(?:^|\r?\n)"
                + re.escape(expected_bytes)
                + rb"(?:\r?\n|$)",
                bytes(output),
            ) is not None

    except OSError:
        return False


def api_ready(token: str | None = None, timeout: int = 30) -> bool:
    """Root API yanıtını kontrol et."""
    if not token:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(
                f"http://{MODEM}:{API_PORT}/v1/status/ddos",
                headers={"X-EX520-Token": token},
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                body = json.load(response)
            if response.status == 200 and isinstance(body, dict):
                return True
        except (OSError, ValueError, urllib.error.URLError):
            time.sleep(0.5)
    return False


def ssh_ready(timeout: int = 15) -> bool:
    """SSH anahtarıyla UID 0 erişimini kontrol et."""
    if not SSH_PRIVATE_KEY_FILE.is_file():
        return False
    try:
        result = subprocess.run(
            [
                "ssh", "-i", str(SSH_PRIVATE_KEY_FILE),
                "-p", str(SSH_PORT), "-o", "BatchMode=yes",
                "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=3",
                "-o", "StrictHostKeyChecking=no",
                "-o", f"UserKnownHostsFile={os.devnull}",
                f"root@{MODEM}", "cat /proc/self/status",
            ],
            check=False,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and re.search(
        br"(?:^|\n)Uid:\s+0\s+0\s+0\s+0(?:\n|$)", result.stdout
    ) is not None


def web_root_ready() -> bool:
    expression = """new Promise(resolve => {
      if (!window.$?.dm) return resolve(false);
      $.dm.get({oid:'DEV2_WEBLOGINUSER',data:{},callback:{
        success:d=>resolve(String(d.loginRole)==='1'),fail:()=>resolve(false),error:()=>resolve(false)}});
    })"""
    return evaluate(expression) is True


def web_backend_root_ready() -> bool:
    """Root kullanıcı nesnesinin backend üzerinden erişilebilirliğini kontrol et."""
    expression = """new Promise(resolve => {
      if (!window.$?.dm) return resolve(false);
      $.dm.get({oid:'DEV2_USERS_USER',data:{stack:'1,0,0,0,0,0'},callback:{
        success:d=>resolve(Boolean(d) && (Object.prototype.hasOwnProperty.call(d,'enable') ||
          Object.prototype.hasOwnProperty.call(d,'localAccessCapable') ||
          Object.prototype.hasOwnProperty.call(d,'allowed_LA_Protocols'))),
        fail:()=>resolve(false),error:()=>resolve(false)}});
    })"""
    return evaluate(expression) is True


def web_port_mirror_ready() -> bool:
    """Port Mirror nesnesinin stok backend üzerinden okunabildiğini kontrol et."""
    expression = """new Promise(resolve => {
      if (!window.$?.dm) return resolve(false);
      $.dm.get({oid:'DEV2_PORT_MIRROR',data:{},callback:{
        success:d=>resolve(Boolean(d) && Object.prototype.hasOwnProperty.call(d,'enable')),
        fail:()=>resolve(false),error:()=>resolve(false)}});
    })"""
    return evaluate(expression) is True


def web_packet_capture_ready() -> bool:
    """Packet Capture nesnesinin stok backend üzerinden okunabildiğini kontrol et."""
    expression = """new Promise(resolve => {
      if (!window.$?.dm) return resolve(false);
      $.dm.get({oid:'DEV2_PACKET_CAPTURE',data:{},callback:{
        success:d=>resolve(Boolean(d) && Object.prototype.hasOwnProperty.call(d,'enable')),
        fail:()=>resolve(false),error:()=>resolve(false)}});
    })"""
    return evaluate(expression) is True


def web_diagnostic_pages_ready() -> bool:
    """Stok tanılama sayfalarının HTTP katmanında erişilebilirliğini kontrol et."""
    expression = """Promise.all([
      ['/main/portMirror.htm', 'DEV2_PORT_MIRROR'],
      ['/main/packetCapture.htm', 'DEV2_PACKET_CAPTURE'],
      ['/main/cwmp.htm', 'DEV2_MANAGEMENT_SERVER']
    ].map(async ([path, marker]) => {
      const response = await fetch(path, {cache:'no-store'});
      const body = await response.text();
      return response.status === 200 && body.includes(marker) &&
        !body.includes('pc-login-password') && !body.includes('406 Not Acceptable');
    })).then(results => results.every(Boolean))
      .catch(() => false)"""
    return evaluate(expression) is True


def web_system_tools_ready() -> bool:
    """Sistem Araçları altındaki stok sayfaların gerçek içeriğini kontrol et."""
    pages = (
        "time", "ledSchedule", "diagnostic", "softup", "cwmp", "backNRestore",
        "restartSchedule", "manageCtrl", "log", "tr369", "snmp", "stat",
        "applicationList", "portMirror", "packetCapture", "sectionSettings",
    )
    paths = json.dumps([f"/main/{page}.htm" for page in pages])
    expression = f"""Promise.all({paths}.map(async path => {{
      const response = await fetch(path, {{cache:'no-store'}});
      const body = await response.text();
      return response.status === 200 && body.length > 200 &&
        !body.includes('pc-login-password') && !body.includes('406 Not Acceptable');
    }})).then(results => results.every(Boolean)).catch(() => false)"""
    return evaluate(expression) is True


def web_root_features_ready() -> bool:
    """Panel Root oturumunun bütün zorunlu yeteneklerini doğrula."""
    return all((
        web_root_ready(),
        web_backend_root_ready(),
        web_port_mirror_ready(),
        web_packet_capture_ready(),
        web_diagnostic_pages_ready(),
        web_system_tools_ready(),
        web_hidden_menu_ready(),
    ))


def web_hidden_menu_ready() -> bool:
    """Stok tanılama menüsü üzerindeki ISP kısıtının kaldırıldığını kontrol et."""
    return evaluate(
        "typeof INCLUDE_TTNET_PAGE_RESTRICT !== 'undefined' && "
        "INCLUDE_TTNET_PAGE_RESTRICT === 0"
    ) is True


def print_access_details(bundle: Bundle) -> None:
    refresh_ssh_known_host()
    print("", flush=True)
    print("ROOT ERİŞİM BİLGİLERİ", flush=True)
    print(f"  Modem:          {MODEM}", flush=True)
    print("  Kullanıcı adı:  root", flush=True)
    print(f"  Web panel:      root / {bundle.shell_password[:32]}", flush=True)
    print(f"  Port Mirror:    http://{MODEM}/main/portMirror.htm", flush=True)
    print(f"  Paket yakalama: http://{MODEM}/main/packetCapture.htm", flush=True)
    print(f"  CWMP:           http://{MODEM}/main/cwmp.htm", flush=True)
    print(
        f"  SSH:            ssh -i {SSH_PRIVATE_KEY_FILE} "
        f"-o UserKnownHostsFile={SSH_KNOWN_HOSTS_FILE} "
        f"-o StrictHostKeyChecking=accept-new -p {SSH_PORT} root@{MODEM}",
        flush=True,
    )
    print("  SSH doğrulama:  Üretilen özel anahtar (parola girişi kapalı)", flush=True)
    print(f"  Telnet:         telnet {MODEM} 2323", flush=True)
    print("  Telnet kullanıcı: root", flush=True)
    print(f"  Telnet parola:  {bundle.shell_password}", flush=True)
    print("  Web oturumu:     Gerçek root hesabı, rol 1 ve backend erişimi", flush=True)
    print(f"  Özel dosyalar:  {STATE_DIR}", flush=True)


def login_panel_root(password: str, timeout: int = 25) -> bool:
    """Kontrollü tarayıcıyı stok panelde gerçek root hesabına geçir."""
    panel_password = password[:32]
    try:
        evaluate("""(() => {
          if (window.$?.dm) $.dm.cgi({oid:'/cgi/logout',ajax:{async:false}});
          location.reload();
          return true;
        })()""")
    except (OSError, RuntimeError, SystemExit, websocket.WebSocketException):
        clear_panel_session()

    deadline = time.monotonic() + timeout
    attempted = False
    takeover_confirmed = False
    while time.monotonic() < deadline:
        if not attempted:
            expression = f"""(() => {{
              const username = document.querySelector('#pc-login-user');
              const password = document.querySelector('#pc-login-password');
              const button = document.querySelector('#pc-login-btn');
              if (!username || !password || !button) return false;
              username.value = 'root';
              password.value = {json.dumps(panel_password)};
              username.dispatchEvent(new Event('input', {{bubbles:true}}));
              password.dispatchEvent(new Event('input', {{bubbles:true}}));
              button.click();
              return true;
            }})()"""
            try:
                attempted = evaluate(expression) is True
            except (OSError, RuntimeError, SystemExit, websocket.WebSocketException):
                pass
        if attempted:
            try:
                if not takeover_confirmed:
                    takeover_confirmed = evaluate("""(() => {
                      const confirm = document.querySelector('#confirm-yes');
                      if (!confirm || !confirm.offsetParent) return false;
                      confirm.click();
                      return true;
                    })()""") is True
                if web_root_features_ready():
                    return True
            except (OSError, RuntimeError, SystemExit, websocket.WebSocketException):
                pass
        time.sleep(1)
    return False



def existing_install_ready(bundle, attempts: int = 5, delay: float = 1.0) -> bool:
    """Mevcut kurulumun durumunu kontrol et."""
    attempts = max(1, int(attempts))

    for attempt in range(1, attempts + 1):
        pre_root = root_ready(bundle.shell_password, timeout=3)
        pre_api = api_ready(bundle.api_token, timeout=3)
        pre_ssh = ssh_ready(timeout=5)
        pre_panel = port_state(80)
        pre_tr069 = port_state(8443)

        pre_release = (
            remote_release_matches(
                bundle.shell_password,
                VERSION,
                timeout=3,
            )
            if pre_root
            else False
        )

        print(
            f"[DURUM] deneme {attempt}/{attempts}: "
            f"root={pre_root} "
            f"api={pre_api} "
            f"ssh={pre_ssh} "
            f"panel={pre_panel} "
            f"tr069={pre_tr069} "
            f"release={pre_release}",
            flush=True,
        )

        if (
            pre_root
            and pre_api
            and pre_ssh
            and pre_panel == "open"
            and pre_tr069 != "open"
            and pre_release
        ):
            return True

        if attempt < attempts:
            time.sleep(delay)

    return False


def install() -> None:
    enforce_supported_device()
    configure_device_state()

    pre_lifemote = lifemote_state()

    # Devam eden kurulum özgün Lifemote adresini değiştirmiş olabilir.
    pre_existing_root = root_ready(
        shell_password(),
        timeout=2,
    )

    backup_known = (
        pre_lifemote is not None
        and not pre_existing_root
        and not lifemote_state_is_managed(pre_lifemote)
    )

    lifemote_backup = lifemote_backup_bytes(
        pre_lifemote,
        known=backup_known,
    )

    if backup_known:
        save_known_lifemote_backup(lifemote_backup)
        print(
            "[YEDEK] Kaldırma işlemi için özgün Lifemote durumu kaydedildi.",
            flush=True,
        )
    elif lifemote_state_is_managed(pre_lifemote):
        saved_backup = known_local_lifemote_backup()
        if saved_backup is not None:
            lifemote_backup = saved_backup
            backup_known = True
            print(
                "[YEDEK] Kesilen önceki kurulumun doğrulanmış Lifemote "
                "yedeği kullanılıyor.",
                flush=True,
            )
        else:
            print(
                "[YEDEK] Özgün Lifemote durumu doğrulanamadı. Geçerli eski "
                "yedek yoksa kaldırma işlemi değişiklik yapmadan duracak.",
                flush=True,
            )
    else:
        print(
            "[YEDEK] Özgün Lifemote durumu doğrulanamadı. Geçerli eski "
            "yedek yoksa kaldırma işlemi değişiklik yapmadan duracak.",
            flush=True,
        )

    bind = local_ip()
    bundle = build_bundle(
        bind,
        lifemote_backup=lifemote_backup,
    )
    print(f"[BİLGİ] EX520 tek tuş root {VERSION}", flush=True)
    print(f"[AĞ] modem={MODEM} aktarım_adresi={bind}:{PORT}", flush=True)

    # Açılış sonrasında servislerin hazır olması birkaç saniye sürebilir.
    if existing_install_ready(bundle):
        pre_web = False

        try:
            pre_web = web_root_ready()
        except (
            OSError,
            RuntimeError,
            SystemExit,
            websocket.WebSocketException,
        ):
            pass

        pre_backend_web = False
        try:
            pre_backend_web = web_backend_root_ready()
        except (
            OSError,
            RuntimeError,
            SystemExit,
            websocket.WebSocketException,
        ):
            pass

        pre_features = False
        try:
            pre_features = web_root_features_ready()
        except (
            OSError,
            RuntimeError,
            SystemExit,
            websocket.WebSocketException,
        ):
            pass

        if pre_web and pre_backend_web and pre_features:
            print(
                "[DURUM] Kurulum zaten sağlıklı; modem üzerinde değişiklik yapılmadı.",
                flush=True,
            )
            disable_legacy_watcher()
            print_access_details(bundle)
            return

        try:
            if login_panel_root(bundle.shell_password):
                print(
                    "[ONARIM] Root servisleri sağlıklı; web root rolü yenilendi.",
                    flush=True,
                )
                disable_legacy_watcher()
                print_access_details(bundle)
                return
        except (
            OSError,
            RuntimeError,
            SystemExit,
            websocket.WebSocketException,
        ):
            pass

        raise SystemExit(
            "EKSİK_ROOT: UID 0, SSH ve root API sağlıklı; ancak panel "
            "Root veya stok Sistem Araçlarının tamamı doğrulanamadı."
        )
    else:
        print(
            "[DURUM] Mevcut kurulum doğrulanamadı; kurulum dosyaları yenilenecek.",
            flush=True,
        )

    if ssh_ready(timeout=5):
        print("[GÜNCELLEME] Mevcut UID 0 SSH kanalı kullanılıyor.", flush=True)
        if not upgrade_over_existing_ssh(bundle):
            raise SystemExit("SSH üzerinden bütünlük kontrollü güncelleme başarısız.")
        if not existing_install_ready(bundle, attempts=6, delay=2):
            raise SystemExit("SSH güncellemesi sonrası root servisleri doğrulanamadı.")
        time.sleep(2)
        if not login_panel_root(bundle.shell_password):
            raise SystemExit(
                "SSH güncellemesi sonrası panel Root ve stok sayfaların "
                "tamamı doğrulanamadı."
            )
        print(
            "[DOĞRULAMA] Panel Root, backend ve tüm stok Sistem Araçları hazır.",
            flush=True,
        )
        disable_legacy_watcher()
        print_access_details(bundle)
        return

    server, complete, snapshot = serve_bundle(bind, bundle)
    firewall_rule = None
    try:
        health = f"http://{bind}:{PORT}/health"
        with urllib.request.urlopen(health, timeout=2) as response:
            if response.read().strip() != b"OK":
                raise SystemExit("Yerel aktarım sunucusu beklenmeyen yanıt verdi.")
        print("[SUNUCU] Yerel aktarım sunucusu hazır.", flush=True)

        url = f"http://{bind}:{PORT}/{bundle.nonce}/install.sh"
        print(f"[TETİK] Lifemote aktarımı başlatılıyor: {url}", flush=True)
        if not activate_lifemote_with_fresh_login(url):
            raise SystemExit("Panel Lifemote kurulum isteğini reddetti.")

        transfer_started = time.monotonic()
        stall_deadline = transfer_started + BUNDLE_STALL_TIMEOUT
        next_retry = transfer_started + BUNDLE_RETRY_INTERVAL
        trigger_attempts = 1
        last_fetched_count = -1
        timeout_reason = None
        firewall_attempted = False

        while not complete.wait(1):
            fetched, missing = snapshot()
            now = time.monotonic()

            if len(fetched) > last_fetched_count:
                last_fetched_count = len(fetched)
                stall_deadline = now + BUNDLE_STALL_TIMEOUT
                next_retry = now + BUNDLE_RETRY_INTERVAL

            if (
                not fetched
                and not firewall_attempted
                and now - transfer_started >= FIREWALL_PROBE_TIMEOUT
            ):
                firewall_attempted = True
                firewall_rule = open_temporary_firewall(bind)
                if firewall_rule is not None:
                    print(
                        "[GÜVENLİK DUVARI] Geçici izin açıldı; aktarım yeniden "
                        "tetikleniyor.",
                        flush=True,
                    )
                    if not activate_lifemote(url):
                        raise SystemExit(
                            "Geçici güvenlik duvarı izninden sonra Lifemote "
                            "tetiklenemedi."
                        )
                    trigger_attempts += 1
                    next_retry = now + BUNDLE_RETRY_INTERVAL

            if (
                missing
                and now >= next_retry
                and trigger_attempts < BUNDLE_MAX_TRIGGER_ATTEMPTS
            ):
                trigger_attempts += 1
                print(
                    f"[YENİDEN TETİK] Aktarım sürdürülüyor "
                    f"({trigger_attempts}/{BUNDLE_MAX_TRIGGER_ATTEMPTS}).",
                    flush=True,
                )
                try:
                    trigger(url)
                except (
                    OSError,
                    RuntimeError,
                    SystemExit,
                    websocket.WebSocketException,
                ):
                    print(
                        "[YENİDEN TETİK] Panel geçici olarak erişilemiyor; "
                        "aktarım sunucusu beklemeye devam ediyor.",
                        flush=True,
                    )
                next_retry = now + BUNDLE_RETRY_INTERVAL

            if now >= stall_deadline:
                timeout_reason = (
                    f"{BUNDLE_STALL_TIMEOUT} saniye boyunca yeni dosya alınmadı"
                )
                break

            if now - transfer_started >= BUNDLE_TOTAL_TIMEOUT:
                timeout_reason = (
                    f"toplam aktarım {BUNDLE_TOTAL_TIMEOUT} saniyeyi aştı"
                )
                break

        if timeout_reason is not None:
            fetched, missing = snapshot()
            detail = [
                "Modem kurulum dosyalarının tamamını alamadı.",
                f"Neden: {timeout_reason}",
                f"Alınan ({len(fetched)}): "
                f"{', '.join(fetched) if fetched else '<yok>'}",
                f"Sunucudan istenmeyen veya cihazda zaten bulunan "
                f"({len(missing)}): "
                f"{', '.join(missing) if missing else '<yok>'}",
            ]

            if not fetched:
                detail.append(
                    "Tanı: Bilgisayara aktarım isteği ulaşmadı. Lifemote "
                    "çalışmasını ve TCP/18084 güvenlik duvarını kontrol edin."
                )
            elif fetched == ["install.sh"]:
                detail.append(
                    "Tanı: install.sh alındı ancak diğer dosyalar istenmedi."
                )
            else:
                detail.append(
                    "Tanı: Kurulum yarıda durdu. Yeniden çalıştırarak eksik "
                    "dosyaları tamamlayın."
                )

            raise SystemExit("\n".join(detail))

        print(
            "[DOĞRULAMA] Aktarım tamamlandı; root servisleri kontrol ediliyor.",
            flush=True,
        )

        if not root_ready(bundle.shell_password):
            raise SystemExit("UID 0 shell doğrulanamadı.")

        if not api_ready(bundle.api_token):
            raise SystemExit("LAN root API servisi doğrulanamadı.")

        if not ssh_ready():
            raise SystemExit("SSH üzerinden UID 0 doğrulanamadı.")

        print(
            "[KALICILIK] Lifemote açılış bağlantısı yazılıyor.",
            flush=True,
        )

        if not trigger(PERSISTENT_HOOK_URL):
            raise SystemExit(
                "Kalıcı Lifemote bağlantısı modem tarafından reddedildi."
            )

        time.sleep(1)

        persistent_state = lifemote_state()

        if (
            persistent_state is None
            or persistent_state.get("enable") != "1"
            or persistent_state.get("URL") != PERSISTENT_HOOK_URL
        ):
            raise SystemExit(
                "Kalıcı Lifemote bağlantısı doğrulanamadı: "
                f"{persistent_state!r}"
            )

        print(
            f"[KALICILIK] Doğrulandı: {PERSISTENT_HOOK_URL}",
            flush=True,
        )

        time.sleep(2)
        if not login_panel_root(bundle.shell_password):
            raise SystemExit(
                "Panel Root, backend veya stok Sistem Araçlarının tamamı "
                "doğrulanamadı."
            )
        print(
            "[DOĞRULAMA] Panel Root, backend ve tüm stok Sistem Araçları hazır.",
            flush=True,
        )

        panel_state = port_state(80)
        tr069_state = port_state(8443)
        if panel_state != "open":
            raise SystemExit(f"Modem paneline ulaşılamıyor: TCP/80 durumu {panel_state}.")
        if tr069_state == "open":
            raise SystemExit("TR-069 kilidi doğrulanamadı: TCP/8443 açık.")
        print(f"[DOĞRULAMA] TCP/8443 erişime kapalı ({tr069_state}).", flush=True)
    finally:
        server.shutdown()
        server.server_close()
        close_temporary_firewall(firewall_rule)

    disable_legacy_watcher()
    print("TAMAMLANDI: UID 0 Telnet/SSH, kalıcı Root paneli ve TR-069 kilidi doğrulandı.")
    print_access_details(bundle)


def chrome_binary() -> str:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if found := shutil.which(name):
            return found
    fallback = Path("/opt/google/chrome/chrome")
    if fallback.is_file():
        return str(fallback)
    if sys.platform == "darwin":
        for fallback in (
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            Path.home() / "Applications/Chromium.app/Contents/MacOS/Chromium",
        ):
            if fallback.is_file():
                return str(fallback)
    if os.name == "nt":
        for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"),
                     os.environ.get("LOCALAPPDATA")):
            if not base:
                continue
            for relative in ("Google/Chrome/Application/chrome.exe",
                             "Chromium/Application/chrome.exe"):
                fallback = Path(base) / relative
                if fallback.is_file():
                    return str(fallback)
    raise SystemExit("Chrome veya Chromium bulunamadı.")


def open_panel() -> None:
    VISIBLE_PROFILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    command = [
        chrome_binary(), f"--remote-debugging-port={VISIBLE_CDP_PORT}",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-allow-origins=http://127.0.0.1:{VISIBLE_CDP_PORT}",
        f"--user-data-dir={VISIBLE_PROFILE}", "--no-first-run",
        "--no-default-browser-check", f"http://{MODEM}/",
    ]
    subprocess.Popen(command, start_new_session=os.name != "nt")


def port_state(port: int) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        code = sock.connect_ex((MODEM, port))
    if code == 0:
        return "open"
    if code == errno.ECONNREFUSED:
        return "closed"
    if code in {errno.ETIMEDOUT, errno.EAGAIN, errno.EWOULDBLOCK}:
        return "timeout/filtered"
    if code in {errno.EHOSTUNREACH, errno.ENETUNREACH}:
        return "unreachable"
    return f"error:{code}"


def status() -> None:
    configure_device_state()
    ports = {str(port): port_state(port) for port in (80, 2222, 2323, 8443, 18080)}
    result: dict[str, object] = {
        "modem": MODEM,
        "bind": local_ip(),
        "ports": ports,
        "web_root": False,
        "web_backend_root": False,
        "port_mirror_backend": False,
        "packet_capture_backend": False,
        "diagnostic_pages": False,
        "system_tools_pages": False,
        "complete_panel_root": False,
        "hidden_menu_unlocked": False,
        "custom_web_pages": 0,
        "tr069_locked": ports["80"] == "open" and ports["8443"] != "open",
    }
    try:
        result["web_root"] = web_root_ready()
        result["web_backend_root"] = web_backend_root_ready()
        result["port_mirror_backend"] = web_port_mirror_ready()
        result["packet_capture_backend"] = web_packet_capture_ready()
        result["diagnostic_pages"] = web_diagnostic_pages_ready()
        result["system_tools_pages"] = web_system_tools_ready()
        result["hidden_menu_unlocked"] = web_hidden_menu_ready()
        result["complete_panel_root"] = all((
            result["web_root"],
            result["web_backend_root"],
            result["port_mirror_backend"],
            result["packet_capture_backend"],
            result["diagnostic_pages"],
            result["system_tools_pages"],
            result["hidden_menu_unlocked"],
        ))
    except (OSError, RuntimeError, SystemExit, websocket.WebSocketException):
        pass
    token = API_TOKEN_FILE.read_text(encoding="utf-8").strip() if API_TOKEN_FILE.is_file() else None
    result["root_api"] = api_ready(token, timeout=2)
    result["ssh_root"] = ssh_ready(timeout=5)
    result["root_api_probe"] = "authenticated HTTP /v1/status/ddos"
    result["version"] = VERSION
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _open_authenticated_root_shell(
    secret: str,
    timeout: float = 8,
):
    connection = socket.create_connection(
        (MODEM, 2323),
        timeout=3,
    )
    connection.setblocking(False)

    received = bytearray()
    deadline = time.monotonic() + timeout

    while b"username:" not in received and time.monotonic() < deadline:
        readable, _, _ = select.select(
            [connection],
            [],
            [],
            0.2,
        )

        if readable:
            chunk = connection.recv(4096)

            if not chunk:
                break

            received.extend(chunk)

    if b"username:" not in received:
        connection.close()
        raise SystemExit(
            "Root shell kullanıcı adı istemi alınamadı."
        )

    connection.sendall(b"root\n")

    received = bytearray()
    deadline = time.monotonic() + timeout

    while b"password:" not in received and time.monotonic() < deadline:
        readable, _, _ = select.select([connection], [], [], 0.2)

        if readable:
            chunk = connection.recv(4096)

            if not chunk:
                break

            received.extend(chunk)

    if b"password:" not in received:
        connection.close()
        raise SystemExit("Root shell parola istemi alınamadı.")

    connection.sendall((secret + "\n").encode())

    shell = bytearray()
    deadline = time.monotonic() + timeout

    while (
        not re.search(
            br"(?:^|[\r\n])[^\r\n]*#\s*$",
            shell,
        )
        and time.monotonic() < deadline
    ):
        readable, _, _ = select.select(
            [connection],
            [],
            [],
            0.2,
        )

        if readable:
            chunk = connection.recv(4096)

            if not chunk:
                break

            shell.extend(chunk)

    if not re.search(
        br"(?:^|[\r\n])[^\r\n]*#\s*$",
        shell,
    ):
        connection.close()
        raise SystemExit(
            "Root shell kimlik doğrulaması başarısız."
        )

    return connection


def _remote_lifemote_backup(secret: str) -> dict[str, object]:
    connection = _open_authenticated_root_shell(secret)

    try:
        connection.sendall(
            (
                "/bin/echo __EX520_BACKUP_BEGIN__; "
                "/bin/cat /var/run/misc/misc_rw/"
                + LIFEMOTE_BACKUP_NAME
                + " 2>/dev/null; "
                "/bin/echo __EX520_BACKUP_END__; "
                "exit\n"
            ).encode()
        )

        output = bytearray()
        deadline = time.monotonic() + 8

        while time.monotonic() < deadline:
            readable, _, _ = select.select(
                [connection],
                [],
                [],
                0.2,
            )

            if readable:
                chunk = connection.recv(4096)

                if not chunk:
                    break

                output.extend(chunk)

    finally:
        connection.close()

    begin = b"__EX520_BACKUP_BEGIN__"
    finish = b"__EX520_BACKUP_END__"

    begin_at = output.rfind(begin)

    if begin_at < 0:
        raise SystemExit(
            "KALDIRMA_DURDU: Lifemote yedek işareti bulunamadı; "
            "değişiklik yapılmadı."
        )

    finish_at = output.find(
        finish,
        begin_at + len(begin),
    )

    if finish_at < 0:
        raise SystemExit(
            "KALDIRMA_DURDU: Lifemote yedeği eksik; değişiklik yapılmadı."
        )

    body = bytes(
        output[
            begin_at + len(begin):
            finish_at
        ]
    ).strip()

    try:
        value = json.loads(body.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SystemExit(
            "KALDIRMA_DURDU: Lifemote yedeği geçersiz; değişiklik yapılmadı."
        )

    if not isinstance(value, dict):
        raise SystemExit(
            "KALDIRMA_DURDU: Lifemote yedeğinin türü geçersiz; "
            "değişiklik yapılmadı."
        )

    return value


def _run_remote_rollback(secret: str) -> None:
    connection = _open_authenticated_root_shell(secret)

    try:
        connection.sendall(
            b"/bin/sh /var/run/misc/misc_rw/rollback.sh\n"
        )

        output = bytearray()
        deadline = time.monotonic() + 15

        while time.monotonic() < deadline:
            readable, _, _ = select.select(
                [connection],
                [],
                [],
                0.2,
            )

            if readable:
                chunk = connection.recv(4096)

                if not chunk:
                    break

                output.extend(chunk)

                if b"ROLLBACK_OK" in output:
                    break

    finally:
        connection.close()

    if b"ROLLBACK_OK" not in output:
        raise SystemExit("Geri alma işlemi tamamlandığını doğrulamadı.")


def uninstall() -> None:
    # Geri alma işleminden önce cihazı yeniden doğrula.
    if not panel_login_ready():
        if controlled_panel_present():
            wait_for_panel_login()
        else:
            open_panel()
            wait_for_panel_login()

    enforce_supported_device()
    configure_device_state()

    secret = existing_shell_password()
    backup = _remote_lifemote_backup(secret)

    if (
        backup.get("schema") != 1
        or backup.get("known") is not True
    ):
        raise SystemExit(
            "KALDIRMA_DURDU: Özgün Lifemote durumu doğrulanamıyor. "
            "Modemde değişiklik yapılmadı. Bu kurulum geçerli kaldırma "
            "yedeğinden önce yapılmış veya eski bir sürümden yükseltilmiş."
        )

    original_enable = str(backup.get("enable", ""))
    original_url = str(backup.get("URL", ""))

    print(
        "[KALDIRMA] Özgün Lifemote durumu geri yükleniyor.",
        flush=True,
    )

    if not set_lifemote_state(
        original_enable,
        original_url,
    ):
        raise SystemExit(
            "KALDIRMA_DURDU: Özgün Lifemote durumu reddedildi; "
            "kurulum dosyaları kaldırılmadı."
        )

    time.sleep(1)

    restored = lifemote_state()

    expected_enable = (
        "1"
        if original_enable.strip().lower()
        in {"1", "true", "yes", "on"}
        else "0"
    )

    if (
        restored is None
        or restored.get("enable") != expected_enable
        or restored.get("URL") != original_url
    ):
        raise SystemExit(
            "KALDIRMA_DURDU: Özgün Lifemote durumu doğrulanamadı: "
            f"{restored!r}. Kurulum dosyaları kaldırılmadı."
        )

    print(
        "[KALDIRMA] Özgün Lifemote durumu doğrulandı.",
        flush=True,
    )

    _run_remote_rollback(secret)

    disable_legacy_watcher()

    for path in (
        PASSWORD_FILE, API_TOKEN_FILE, SSH_PRIVATE_KEY_FILE, SSH_PUBLIC_KEY_FILE,
        SSH_KNOWN_HOSTS_FILE, LOCAL_LIFEMOTE_BACKUP_FILE,
    ):
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    print(
        "TAMAMLANDI: Kalıcı kurulum dosyaları ve root dinleyicileri kaldırıldı. "
        "Stok güvenlik duvarı ve süreç durumunun kurulması için modemi yeniden "
        "başlatın.",
        flush=True,
    )



def panel_login_ready() -> bool:
    """Panel oturumunun açık olup olmadığını kontrol et."""
    expression = r"""
new Promise(resolve => {
    if (!window.$?.dm) {
        return resolve(false);
    }

    $.dm.get({
        oid: 'DEV2_DEV_INFO',
        data: {
            hardwareVersion: '',
            softwareVersion: ''
        },
        callback: {
            success: d => resolve(
                !!d &&
                typeof d.hardwareVersion !== 'undefined' &&
                typeof d.softwareVersion !== 'undefined'
            ),
            fail: () => resolve(false),
            error: () => resolve(false)
        }
    });
})
"""
    try:
        return evaluate(expression) is True
    except (
        OSError,
        RuntimeError,
        SystemExit,
        websocket.WebSocketException,
    ):
        return False


def dismiss_default_password_prompt(timeout: int = 15) -> bool:
    """Varsayılan parola korunacaksa stok uyarıyı desteklenen CGI ile geç."""
    snapshot = panel_state_snapshot()
    if not snapshot or not snapshot.get("passwordChange"):
        return True

    expression = r"""
new Promise(resolve => {
    if (!window.$?.dm) return resolve(false);
    try {
        $.dm.setSync({oid:'DEV2_WEBLOGINUSER', data:{loginRole:'2'}});
    } catch (_) {
        return resolve(false);
    }
    $.dm.cgi({
        oid:'/cgi/changeDftPwd',
        data:{skipFlag:'1'},
        callback:{
            success:() => resolve(true),
            fail:() => resolve(false),
            error:() => resolve(false)
        }
    });
})
"""
    if evaluate(expression) is not True:
        return False
    evaluate("location.reload(); true")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = panel_state_snapshot()
        if snapshot and not snapshot.get("passwordChange") and panel_login_ready():
            return True
        time.sleep(1)
    return False



def panel_state_snapshot() -> dict[str, object] | None:
    """Giriş alanlarının değerlerini okumadan panel durumunu bul."""
    expression = r"""
(() => {
    const body = String(document.body?.innerText || '').toLowerCase();

    const allPasswordInputs = Array.from(
        document.querySelectorAll('input[type="password"]')
    );

    const isVisible = el => {
        if (!(el instanceof HTMLElement)) {
            return false;
        }

        const style = window.getComputedStyle(el);

        if (
            style.display === 'none' ||
            style.visibility === 'hidden' ||
            Number(style.opacity || '1') === 0
        ) {
            return false;
        }

        const rect = el.getBoundingClientRect();

        return (
            rect.width > 0 &&
            rect.height > 0 &&
            el.getClientRects().length > 0
        );
    };

    const visiblePasswordInputs =
        allPasswordInputs.filter(isVisible).length;

    const passwordChange = visiblePasswordInputs >= 2;

    return {
        url: String(location.href || ''),
        title: String(document.title || ''),
        passwordInputs: visiblePasswordInputs,
        totalPasswordInputs: allPasswordInputs.length,
        passwordChange: passwordChange
    };
})()
"""

    try:
        value = evaluate(expression)
        return value if isinstance(value, dict) else None
    except (
        OSError,
        RuntimeError,
        SystemExit,
        websocket.WebSocketException,
    ):
        return None


def controlled_panel_present() -> bool:
    return panel_state_snapshot() is not None


def try_default_panel_login(timeout: int = 8) -> bool:
    """admin/admin girişini bir kez dene."""
    print("[GİRİŞ] Varsayılan admin/admin bilgileri bir kez deneniyor...", flush=True)

    expression = r"""
(() => {
    const password = document.querySelector('#pc-login-password');
    if (!password) return false;

    const username = document.querySelector('#pc-login-user');
    if (username) {
        username.value = 'admin';
        username.dispatchEvent(new Event('input', {bubbles: true}));
        username.dispatchEvent(new Event('change', {bubbles: true}));
    }

    password.value = 'admin';
    password.dispatchEvent(new Event('input', {bubbles: true}));
    password.dispatchEvent(new Event('change', {bubbles: true}));

    const button = document.querySelector('#pc-login-btn');
    if (!button) return false;
    button.click();
    return true;
})()
"""

    deadline = time.monotonic() + timeout
    attempted = False
    takeover_confirmed = False

    while time.monotonic() < deadline:
        if panel_login_ready():
            if not dismiss_default_password_prompt():
                raise SystemExit("Varsayılan parola uyarısı stok panelde geçilemedi.")
            print("[GİRİŞ] Varsayılan bilgiler kabul edildi.", flush=True)
            return True

        snapshot = panel_state_snapshot()
        if snapshot and not snapshot.get("passwordChange") and not attempted:
            try:
                attempted = evaluate(expression) is True
            except (OSError, RuntimeError, SystemExit, websocket.WebSocketException):
                attempted = False

        if attempted and not takeover_confirmed:
            try:
                takeover_confirmed = evaluate(r"""
(() => {
    const alert = document.querySelector('#alert-container');
    if (!alert || getComputedStyle(alert).display === 'none') return false;
    const text = String(alert.innerText || '');
    if (!text.includes('Aynı anda yalnızca bir cihaz')) return false;
    const button = alert.querySelector('.btn-msg-ok');
    if (!button) return false;
    button.click();
    return true;
})()
""") is True
            except (OSError, RuntimeError, SystemExit, websocket.WebSocketException):
                takeover_confirmed = False

        time.sleep(1)

    try:
        evaluate("""
(() => {
    const password = document.querySelector('#pc-login-password');
    if (password) password.value = '';
    return true;
})()
""")
    except (OSError, RuntimeError, SystemExit, websocket.WebSocketException):
        pass

    print(
        "[GİRİŞ] Varsayılan bilgiler kabul edilmedi. Chrome penceresinde "
        "modem kullanıcı adınızı ve şifrenizi girin. Giriş başarılı olduğunda "
        "kurulum otomatik devam edecek.",
        flush=True,
    )
    return False


def wait_for_panel_login(timeout: int = 600) -> None:
    print(
        f"[GİRİŞ] Panel: http://{MODEM}/",
        flush=True,
    )
    print(
        "[GİRİŞ] Modem kullanıcı adı ve şifrenizle giriş yapın.",
        flush=True,
    )

    deadline = time.monotonic() + timeout
    last_state = None

    while time.monotonic() < deadline:
        # DEV2_DEV_INFO is readable only after a valid login.
        if panel_login_ready():
            if not dismiss_default_password_prompt():
                raise SystemExit("Varsayılan parola uyarısı stok panelde geçilemedi.")
            print(
                "[GİRİŞ] Giriş tamamlandı; cihaz bilgileri okunabiliyor.",
                flush=True,
            )
            return

        snapshot = panel_state_snapshot()

        if snapshot is None:
            state = "waiting-panel"

        elif bool(snapshot.get("passwordChange")):
            state = "password-change"

        elif int(snapshot.get("passwordInputs", 0) or 0) > 0:
            state = "login"

        else:
            state = "loading"

        if state != last_state:
            if state == "waiting-panel":
                print(
                    "[GİRİŞ] Modem panelinin açılması bekleniyor...",
                    flush=True,
                )

            elif state == "login":
                print(
                    "[GİRİŞ] Giriş ekranı algılandı; "
                    "bilgilerinizi girip devam edin.",
                    flush=True,
                )

            elif state == "password-change":
                print(
                    "[GİRİŞ] Yeni şifre belirleme ekranı algılandı; "
                    "işlemi panelden tamamlayın.",
                    flush=True,
                )

            elif state == "loading":
                print(
                    "[GİRİŞ] Panel geçişinin tamamlanması bekleniyor...",
                    flush=True,
                )

            last_state = state

        time.sleep(1)

    raise SystemExit(
        "GİRİŞ_ZAMAN_AŞIMI: Modem panelinde tamamlanmış bir "
        "oturum 10 dakika içinde algılanamadı"
    )


def dry_run() -> None:
    """Modemde değişiklik yapmadan ön kontrolleri çalıştır."""
    print("EX520v Root Aracı - Ön Kontrol", flush=True)

    state = port_state(80)
    print(f"[KONTROL] Modem HTTP durumu: {state}", flush=True)

    if state != "open":
        raise SystemExit(
            f"MODEME_ERİŞİLEMİYOR: http://{MODEM}/ açılamadı."
        )

    if panel_login_ready():
        print("[GİRİŞ] Açık modem oturumu bulundu.", flush=True)

    elif controlled_panel_present():
        print("[TARAYICI] Açık modem paneli bulundu.", flush=True)
        wait_for_panel_login()

    else:
        print("[TARAYICI] Chrome/Chromium açılıyor.", flush=True)
        open_panel()
        wait_for_panel_login()

    fp = enforce_supported_device()

    print(
        "[ÖN KONTROL] Aktarım sunucusu başlatılmadı ve Lifemote ayarı "
        "değiştirilmedi.",
        flush=True,
    )
    print(
        "[ÖN KONTROL] Kurulum bu aşamada başlayabilir.",
        flush=True,
    )
    print(
        f"DRY_RUN_OK: {fp['model']} / "
        f"{fp['hardwareVersion']} / "
        f"{fp['softwareVersion']}",
        flush=True,
    )


def oneclick() -> None:
    print("EX520v Tek Tuş Root Aracı", flush=True)
    print(
        f"Hedef: {SUPPORTED_MODEL} / tüm donanım revizyonları / "
        f"{SUPPORTED_FIRMWARE}",
        flush=True,
    )

    if port_state(80) != "open":
        raise SystemExit(
            f"MODEME_ERİŞİLEMİYOR: http://{MODEM}/ açılamadı."
        )

    if panel_login_ready():
        print("[GİRİŞ] Açık modem oturumu bulundu.", flush=True)

    elif controlled_panel_present():
        print("[TARAYICI] Açık modem paneli bulundu.", flush=True)
        if not try_default_panel_login():
            wait_for_panel_login()

    else:
        print("[TARAYICI] Chrome/Chromium açılıyor...", flush=True)
        open_panel()
        if not try_default_panel_login():
            wait_for_panel_login()

    install()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("oneclick", "dry-run", "install", "status", "panel", "uninstall"),
        default="oneclick",
        nargs="?",
    )
    action = parser.parse_args().action
    {
        "oneclick": oneclick,
        "dry-run": dry_run,
        "install": install,
        "status": status,
        "panel": open_panel,
        "uninstall": uninstall,
    }[action]()


if __name__ == "__main__":
    main()
