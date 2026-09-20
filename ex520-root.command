#!/bin/sh
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$HERE"

PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

if [ -x /opt/homebrew/bin/brew ]; then
    PATH="/opt/homebrew/bin:$PATH"
elif [ -x /usr/local/bin/brew ]; then
    PATH="/usr/local/bin:$PATH"
fi

openssh_ready() {
    command -v ssh-keygen >/dev/null 2>&1 &&
    command -v ssh >/dev/null 2>&1 &&
    command -v ssh-keyscan >/dev/null 2>&1
}

chrome_ready() {
    [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ] ||
    [ -x "$HOME/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ] ||
    [ -x "/Applications/Chromium.app/Contents/MacOS/Chromium" ] ||
    [ -x "$HOME/Applications/Chromium.app/Contents/MacOS/Chromium" ] ||
    command -v chromium >/dev/null 2>&1
}

requirements_ready() {
    command -v python3 >/dev/null 2>&1 &&
    openssh_ready &&
    chrome_ready
}

if ! requirements_ready; then
    if ! command -v brew >/dev/null 2>&1; then
        echo "HATA: Otomatik gereksinim kurulumu için Homebrew bulunamadı."
        echo "Önce https://brew.sh adresinden Homebrew kurup aracı yeniden açın."
        printf '\nBu pencereyi kapatmak için Enter tuşuna basın...'
        read -r _
        exit 1
    fi
    echo "[HAZIRLIK] Eksik sistem gereksinimleri kuruluyor..."
    command -v python3 >/dev/null 2>&1 || brew install python
    openssh_ready || brew install openssh
    if ! chrome_ready; then
        brew install --cask google-chrome
    fi
fi

if ! requirements_ready; then
    echo "HATA: Python 3, Google Chrome veya OpenSSH hazırlanamadı."
    exit 1
fi

if [ ! -d .venv ]; then
    python3 -m venv .venv || {
        command -v brew >/dev/null 2>&1 || {
            echo "HATA: Python sanal ortamı oluşturulamadı ve Homebrew bulunamadı."
            exit 1
        }
        brew install python
        python3 -m venv .venv
    }
fi

if ! .venv/bin/python -c 'import websocket' >/dev/null 2>&1; then
    .venv/bin/python -m pip install --disable-pip-version-check --quiet \
        --no-index --find-links "$HERE/vendor" -r requirements.txt
fi

case "${1-}" in
    "") action=oneclick ;;
    --dry-run) action=dry-run ;;
    --status) action=status ;;
    --panel) action=panel ;;
    --uninstall) action=uninstall ;;
    *)
        echo "Kullanım: ./ex520-root.command [--dry-run|--status|--panel|--uninstall]"
        exit 2
        ;;
esac

set +e
.venv/bin/python ex520_oneclick.py "$action"
status=$?
set -e
printf '\nBu pencereyi kapatmak için Enter tuşuna basın...'
read -r _ || true
exit "$status"
