#!/bin/sh

# Betik Lifemote tarafından misc_rw içinden başlatılır.
login_script=/var/tmp/persistent-root-login.sh
pid_file=/var/run/persistent-local-root.pid
patched_httpd_pid=
panel_root_password='__PANEL_ROOT_PASSWORD__'

# LXC açılış kancasını bekletme.
if [ "${1:-}" != "--daemon" ]; then
    if [ -s "$pid_file" ] && /bin/kill -0 "$(/bin/cat "$pid_file")" 2>/dev/null; then
        exit 0
    fi
    /bin/sh "$0" --daemon >/var/tmp/persistent-local-root.log 2>&1 &
    exit 0
fi

if [ -s "$pid_file" ] && /bin/kill -0 "$(/bin/cat "$pid_file")" 2>/dev/null; then
    exit 0
fi
echo $$ >"$pid_file"
trap '/bin/rm -f "$pid_file"' EXIT

install_tr069_lockdown() {
    /usr/bin/killall -STOP cwmp >/dev/null 2>&1 || true
    /usr/bin/killall -STOP obuspa >/dev/null 2>&1 || true
    /usr/bin/iptables -C INPUT -p tcp --dport 8443 -j DROP 2>/dev/null || \
        /usr/bin/iptables -I INPUT 1 -p tcp --dport 8443 -j DROP
}

install_agent_compat() {
    tmpd_patch=/var/run/misc/misc_rw/patch-tmpd-agent.sh
    libcmm_patch=/var/run/misc/misc_rw/patch-libcmm-all-agent.sh
    [ -x "$tmpd_patch" ] && /bin/sh "$tmpd_patch" >/dev/null 2>&1 || true
    [ -x "$libcmm_patch" ] && /bin/sh "$libcmm_patch" >/dev/null 2>&1 || true
}

restore_feature_traffic() {
    # Eski paketlerden kalan genel kuralları kaldır.
    for port in 80 443 7547 8443 1883 8883 5222; do
        while /usr/bin/iptables -D OUTPUT ! -o br+ -p tcp --dport "$port" -j REJECT 2>/dev/null; do :; done
        if [ -x /usr/bin/ip6tables ]; then
            while /usr/bin/ip6tables -D OUTPUT ! -o br+ -p tcp --dport "$port" -j REJECT 2>/dev/null; do :; done
        fi
    done
    for port in 443 3478; do
        while /usr/bin/iptables -D OUTPUT ! -o br+ -p udp --dport "$port" -j REJECT 2>/dev/null; do :; done
        if [ -x /usr/bin/ip6tables ]; then
            while /usr/bin/ip6tables -D OUTPUT ! -o br+ -p udp --dport "$port" -j REJECT 2>/dev/null; do :; done
        fi
    done
    for proc in /proc/[0-9]*; do
        [ -r "$proc/cmdline" ] || continue
        if /bin/grep -aq '/etc/quantWiFiLoader.sh' "$proc/cmdline"; then
            /bin/kill -CONT "${proc#/proc/}" >/dev/null 2>&1 || true
        fi
    done
}

install_wan_management_lockdown() {
    for port in 22 23 53 80 443 1001 1002 1900 2222 8200 8443 2323 18080; do
        /usr/bin/iptables -C INPUT ! -i br+ -p tcp --dport "$port" -j DROP 2>/dev/null || \
            /usr/bin/iptables -I INPUT 1 ! -i br+ -p tcp --dport "$port" -j DROP
        if [ -x /usr/bin/ip6tables ]; then
            /usr/bin/ip6tables -C INPUT ! -i br+ -p tcp --dport "$port" -j DROP 2>/dev/null || \
                /usr/bin/ip6tables -I INPUT 1 ! -i br+ -p tcp --dport "$port" -j DROP
        fi
    done
    for port in 53 67 137 138 161 500 1900 20002; do
        /usr/bin/iptables -C INPUT ! -i br+ -p udp --dport "$port" -j DROP 2>/dev/null || \
            /usr/bin/iptables -I INPUT 1 ! -i br+ -p udp --dport "$port" -j DROP
        if [ -x /usr/bin/ip6tables ]; then
            /usr/bin/ip6tables -C INPUT ! -i br+ -p udp --dport "$port" -j DROP 2>/dev/null || \
                /usr/bin/ip6tables -I INPUT 1 ! -i br+ -p udp --dport "$port" -j DROP
        fi
    done
}

install_admin_root_role() {
    httpd_pid=$(/bin/pidof httpd 2>/dev/null) || return
    [ -n "$httpd_pid" ] || return
    [ "$httpd_pid" = "$patched_httpd_pid" ] && return

    set -- $(/bin/dd if="/proc/$httpd_pid/mem" bs=1 skip=4325560 count=4 2>/dev/null | \
        /usr/sbin/openssl dgst -sha256 -r 2>/dev/null)
    case "$1" in
        b235bc9cac6139b408bff48434dc326913369ea8a98de6d87ebf70be8c2bc9be)
            echo IACAUg== | /usr/sbin/openssl base64 -d -A | \
                /bin/dd of="/proc/$httpd_pid/mem" bs=1 seek=4325560 count=4 conv=notrunc 2>/dev/null
            ;;
        6f048efdbe0ccddd5bae54c2cc2a016eefe51de703c28bfa80993f8e1f90c5aa)
            ;;
        *)
            return
            ;;
    esac

    set -- $(/bin/dd if="/proc/$httpd_pid/mem" bs=1 skip=4308036 count=4 2>/dev/null | \
        /usr/sbin/openssl dgst -sha256 -r 2>/dev/null)
    case "$1" in
        decf23149eb53e971ad67ab7052e421238fd5fc439505418abcd12f2f44b506b)
            echo HyAD1Q== | /usr/sbin/openssl base64 -d -A | \
                /bin/dd of="/proc/$httpd_pid/mem" bs=1 seek=4308036 count=4 conv=notrunc 2>/dev/null
            ;;
        04ca88f2b88d606239021d6eb03752f117e3f73fb022df93dbe99ab93edf368b)
            ;;
        *)
            return
            ;;
    esac

    # http_login_auth istek rolünü pData+0x50 alanında tutar.
    set -- $(/bin/dd if="/proc/$httpd_pid/mem" bs=1 skip=4327328 count=4 2>/dev/null | \
        /usr/sbin/openssl dgst -sha256 -r 2>/dev/null)
    case "$1" in
        2d22074e0b31adc0fd3b79937cb6e9e676f907854ef86554e923fbc17e238824)
            echo IQCAUg== | /usr/sbin/openssl base64 -d -A | \
                /bin/dd of="/proc/$httpd_pid/mem" bs=1 seek=4327328 count=4 conv=notrunc 2>/dev/null
            ;;
        a05e40ffb29400d590f91ff76826e1b484e532bf643b040ee095653f0f196758)
            ;;
        *)
            return
            ;;
    esac

    # Stok tanı sayfalarını doğrulanmış LAN oturumuna aç.
    set -- $(/bin/dd if="/proc/$httpd_pid/mem" bs=1 skip=4237996 count=4 2>/dev/null | \
        /usr/sbin/openssl dgst -sha256 -r 2>/dev/null)
    case "$1" in
        bae1ecaa1b1ac03f0e9d6ce576c9bb57eef2204134344dcb6fa8796f739b4e44)
            echo EAAAFA== | /usr/sbin/openssl base64 -d -A | \
                /bin/dd of="/proc/$httpd_pid/mem" bs=1 seek=4237996 count=4 conv=notrunc 2>/dev/null
            ;;
        13b734f97639e863e99e77d2381e4a4cf3eb91c7d22a636093fa161778f25389)
            ;;
        *)
            return
            ;;
    esac

    # Doğrulanmış panel oturumlarını stok sayfa yetki filtresinden geçir.
    set -- $(/bin/dd if="/proc/$httpd_pid/mem" bs=1 skip=4241224 count=8 2>/dev/null | \
        /usr/sbin/openssl dgst -sha256 -r 2>/dev/null)
    case "$1" in
        5065c7d3da5d4a0ecb0c4dc831e25e7a8d901bdb87c1a1ecbe65ba3e19a55195)
            echo IACAUsADX9Y= | /usr/sbin/openssl base64 -d -A | \
                /bin/dd of="/proc/$httpd_pid/mem" bs=1 seek=4241224 count=8 conv=notrunc 2>/dev/null
            ;;
        5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac)
            ;;
        *)
            return
            ;;
    esac

    # Eski sürümün özel giriş yollarına uyguladığı hatalı yönlendirmeleri geri al.
    set -- $(/bin/dd if="/proc/$httpd_pid/mem" bs=1 skip=4244616 count=4 2>/dev/null | \
        /usr/sbin/openssl dgst -sha256 -r 2>/dev/null)
    case "$1" in
        80ca2fc1ffcd2354b9e7ac87591c35d0b7238eaa818af01cfac53fd4b929aaf2)
            echo AYAPkQ== | /usr/sbin/openssl base64 -d -A | \
                /bin/dd of="/proc/$httpd_pid/mem" bs=1 seek=4244616 count=4 conv=notrunc 2>/dev/null
            ;;
        e2c29450657bb325ac90a32dd5dc29aca6e41909dafe9e43d8455928b4de854f)
            ;;
        *)
            return
            ;;
    esac

    set -- $(/bin/dd if="/proc/$httpd_pid/mem" bs=1 skip=4244584 count=4 2>/dev/null | \
        /usr/sbin/openssl dgst -sha256 -r 2>/dev/null)
    case "$1" in
        48ba82b117183bf837583db8e434eb6364f12dac8beec024021a545ec6bb41d2)
            echo AUAPkQ== | /usr/sbin/openssl base64 -d -A | \
                /bin/dd of="/proc/$httpd_pid/mem" bs=1 seek=4244584 count=4 conv=notrunc 2>/dev/null
            ;;
        8ed910a7950e0d7b5823ae3ab18164965b293dd3002f09c654a4b8794a16b282)
            ;;
        *)
            return
            ;;
    esac

    set -- $(/bin/dd if="/proc/$httpd_pid/mem" bs=1 skip=4244648 count=4 2>/dev/null | \
        /usr/sbin/openssl dgst -sha256 -r 2>/dev/null)
    case "$1" in
        a176684af253e647b18388e92884d913e94defd9b7de83417e56417b57bf3e5d)
            echo AcAPkQ== | /usr/sbin/openssl base64 -d -A | \
                /bin/dd of="/proc/$httpd_pid/mem" bs=1 seek=4244648 count=4 conv=notrunc 2>/dev/null
            ;;
        5d557f1830f7518cd4c03122779eefc2a620b5946e9b04b943005c9d301316e0)
            ;;
        *)
            return
            ;;
    esac

    # Root rolü stok izin bitinde bulunmasa da sayfaya erişir; diğer roller korunur.
    set -- $(/bin/dd if="/proc/$httpd_pid/mem" bs=1 skip=4252368 count=16 2>/dev/null | \
        /usr/sbin/openssl dgst -sha256 -r 2>/dev/null)
    case "$1" in
        0b81776f55d082cfbc9c04b1b210504a0fb3167689179445504e49ef5d632c3b)
            echo AAAAEuEvQLk/BABxABSfGg== | /usr/sbin/openssl base64 -d -A | \
                /bin/dd of="/proc/$httpd_pid/mem" bs=1 seek=4252368 count=16 conv=notrunc 2>/dev/null
            ;;
        40e6e47d3ac047620d658aa277e13392be2674c42afe79bceb235ba8ce51be61)
            ;;
        *)
            return
            ;;
    esac

    # Packet Capture ve Port Mirror aynı izin değerini kullanır.
    set -- $(/bin/dd if="/proc/$httpd_pid/mem" bs=1 skip=4397356 count=8 2>/dev/null | \
        /usr/sbin/openssl dgst -sha256 -r 2>/dev/null)
    case "$1" in
        ba9ff93ed7386e59eb9862e7401791f507556bbe2c093cae63e2753191cd6f45)
            echo QACAUsADX9Y= | /usr/sbin/openssl base64 -d -A | \
                /bin/dd of="/proc/$httpd_pid/mem" bs=1 seek=4397356 count=8 conv=notrunc 2>/dev/null
            ;;
        0becf359e148792c5ed24ca79a91209e5f15e0f015d2a0b9f4d69c2e82d59f3a)
            ;;
        *)
            return
            ;;
    esac

    # Port Mirror prehook izin verildiğinde 2 döndürür.
    set -- $(/bin/dd if="/proc/$httpd_pid/mem" bs=1 skip=4397708 count=8 2>/dev/null | \
        /usr/sbin/openssl dgst -sha256 -r 2>/dev/null)
    case "$1" in
        2af0714fc7e7e1d6a6da6057a809df6b3c5899ab53fbc1417ceae1ed0e69410d)
            echo QACAUsADX9Y= | /usr/sbin/openssl base64 -d -A | \
                /bin/dd of="/proc/$httpd_pid/mem" bs=1 seek=4397708 count=8 conv=notrunc 2>/dev/null
            ;;
        0becf359e148792c5ed24ca79a91209e5f15e0f015d2a0b9f4d69c2e82d59f3a)
            ;;
        *)
            return
            ;;
    esac
    patched_httpd_pid=$httpd_pid
}

install_panel_root_account() {
    helper=/var/run/misc/misc_rw/ex520-web-root-init
    [ -x "$helper" ] || return
    /bin/busybox echo "$panel_root_password" | "$helper" 2>/dev/null | \
        /bin/busybox tail -n 1 >/var/run/ex520-panel-root.status || true
}

restore_stock_webroot() {
    for page in manageCtrl easyLocalAccess smarthomeEE ddos applicationList portMirror; do
        target="/web/main/${page}.htm"
        while /bin/umount "$target" 2>/dev/null; do :; done
        /bin/busybox rm -f "/var/run/misc/misc_rw/${page}.root.htm" 2>/dev/null || true
    done
    for page in menu top; do
        target="/web/frame/${page}.htm"
        while /bin/umount "$target" 2>/dev/null; do :; done
        /bin/busybox rm -f "/var/run/misc/misc_rw/${page}.root.htm" 2>/dev/null || true
    done
    /bin/busybox rm -f /var/run/misc/misc_rw/ex520-bind-mount \
        /var/run/misc/misc_rw/tpee-enable.sh \
        /var/run/misc/misc_rw/tpee-disable.sh \
        /var/run/misc/misc_rw/oid_str.unlocked.js 2>/dev/null || true
}

install_stock_page_visibility() {
    target=/web/main
    runtime=/var/tmp/ex520-web-main
    patched="$runtime/operateMode.htm"

    if /bin/grep -q " $target " /proc/mounts 2>/dev/null; then
        return
    fi

    [ -r "$target/operateMode.htm" ] || return
    /bin/rm -rf "$runtime"
    /bin/mkdir -p "$runtime" || return
    /bin/cp -a "$target/." "$runtime/" || return
    /bin/sed \
        -e 's@id="en_agent" class="part-separate-m nd"@id="en_agent" class="part-separate-m"@' \
        -e \
        "s@//\$(\"#en_agent\").removeClass('nd');@\$(\"#en_agent\").removeClass('nd');@" \
        "$target/operateMode.htm" >"$patched.new" || return
    [ "$(/bin/grep -c 'id="en_agent" class="part-separate-m"' "$patched.new")" = 1 ] || {
        /bin/rm -f "$patched.new"
        return
    }
    [ "$(/bin/grep -c "^[[:space:]]*\$(\"#en_agent\").removeClass('nd');" "$patched.new")" = 1 ] || {
        /bin/rm -f "$patched.new"
        return
    }
    /bin/mv "$patched.new" "$patched"
    /bin/chmod 440 "$patched"
    /bin/mount --bind "$runtime" "$target"
}

install_stock_menu_unlock() {
    js_target=/web/js
    js_runtime=/var/tmp/ex520-web-js
    patched="$js_runtime/oid_str.js"

    if ! /bin/grep -q " $js_target " /proc/mounts 2>/dev/null; then
        [ -r "$js_target/oid_str.js" ] || return

        /bin/rm -rf "$js_runtime"
        /bin/mkdir -p "$js_runtime" || return
        /bin/cp -a "$js_target/." "$js_runtime/" || return

        /bin/sed \
            's/var INCLUDE_TTNET_PAGE_RESTRICT=1/var INCLUDE_TTNET_PAGE_RESTRICT=0/' \
            "$js_target/oid_str.js" >"$patched.new" || return
        [ "$(/bin/grep -c 'var INCLUDE_TTNET_PAGE_RESTRICT=0' "$patched.new")" = 1 ] || return
        [ "$(/bin/grep -c 'var INCLUDE_TTNET_PAGE_RESTRICT=1' "$patched.new")" = 0 ] || return

        /bin/mv "$patched.new" "$patched"
        /bin/chmod 440 "$patched"
        /bin/mount --bind "$js_runtime" "$js_target" || return
    fi

    frame_target=/web/frame
    frame_runtime=/var/tmp/ex520-web-frame
    menu="$frame_runtime/menu.htm"
    /bin/grep -q " $frame_target " /proc/mounts 2>/dev/null && return

    /bin/rm -rf "$frame_runtime"
    /bin/mkdir -p "$frame_runtime" || return
    /bin/cp -a "$frame_target/." "$frame_runtime/" || return
    /bin/sed \
        "s/self.menuFilter(menulist, menuargs);/menulist.push('cwmp.htm','portMirror.htm','packetCapture.htm'); self.menuFilter(menulist, menuargs);/" \
        "$frame_target/menu.htm" >"$menu.new" || return
    [ "$(/bin/grep -c "menulist.push('cwmp.htm','portMirror.htm','packetCapture.htm')" "$menu.new")" = 1 ] || return
    /bin/mv "$menu.new" "$menu"
    /bin/chmod 440 "$menu"
    /bin/mount --bind "$frame_runtime" "$frame_target"
}

install_root_api() {
    api=/var/run/misc/misc_rw/ex520-root-api
    token=/var/run/misc/misc_rw/root-api.token
    api_pid=/var/run/ex520-root-api.pid
    [ -x "$api" ] && [ -s "$token" ] || return
    # LAN izinlerini eski DROP kurallarının önünde tut.
    while /usr/bin/iptables -D INPUT -i br0 -p tcp --dport 18080 -j ACCEPT 2>/dev/null; do :; done
    while /usr/bin/iptables -D INPUT -p tcp -s 192.168.0.0/24 --dport 18080 -j ACCEPT 2>/dev/null; do :; done
    while /usr/bin/iptables -D INPUT -p tcp -s 192.168.1.0/24 --dport 18080 -j ACCEPT 2>/dev/null; do :; done
    while /usr/bin/iptables -D INPUT -p tcp --dport 18080 -j DROP 2>/dev/null; do :; done
    /usr/bin/iptables -I INPUT 1 -p tcp --dport 18080 -j DROP
    /usr/bin/iptables -I INPUT 1 -i br0 -p tcp --dport 18080 -j ACCEPT
    if [ -s "$api_pid" ] && /bin/kill -0 "$(/bin/cat "$api_pid")" 2>/dev/null && \
       /usr/bin/wget -q -T 3 -O /dev/null \
           --header "X-EX520-Token: $(/bin/cat "$token")" \
           http://127.0.0.1:18080/v1/status/ddos 2>/dev/null; then
        return
    fi

    if [ -s "$api_pid" ]; then
        /bin/kill "$(/bin/cat "$api_pid")" 2>/dev/null || true
    fi
    /bin/rm -f "$api_pid"

    # Takılı kalan dmcli alt süreci API soketini devralmış olabilir.
    inode=$(/usr/bin/awk '$2 ~ /:46A0$/ && $4 == "0A" {print $10; exit}' \
        /proc/net/tcp /proc/net/tcp6 2>/dev/null) || inode=
    if [ -n "$inode" ]; then
        for proc in /proc/[0-9]*; do
            [ -d "$proc/fd" ] || continue
            if /bin/ls -l "$proc/fd" 2>/dev/null | \
               /bin/grep -q "socket:\[$inode\]"; then
                /bin/kill "${proc#/proc/}" 2>/dev/null || true
            fi
        done
    fi
    "$api" >/var/tmp/ex520-root-api.log 2>&1 &
    echo $! >"$api_pid"
}

install_ssh() {
    sshd=/var/run/misc/misc_rw/ex520-dropbear
    authorized=/var/run/misc/misc_rw/root-authorized-keys
    root_home=/var/run/misc/misc_rw/root-home
    runtime_host_key=/var/tmp/dropbear/dropbear_rsa_host_key
    host_key=/var/run/misc/misc_rw/ex520-dropbear-rsa-host-key
    ssh_pid=/var/run/ex520-dropbear.pid

    [ -x "$sshd" ] && [ -s "$authorized" ] || return
    if [ ! -s "$host_key" ] && [ -s "$runtime_host_key" ]; then
        /bin/cp "$runtime_host_key" "$host_key" || return
        /bin/chmod 600 "$host_key"
    fi
    [ -s "$host_key" ] || return

    /bin/mkdir -p "$root_home/.ssh"
    /bin/chmod 700 "$root_home" "$root_home/.ssh"
    /bin/cp "$authorized" "$root_home/.ssh/authorized_keys"
    /bin/chmod 600 "$root_home/.ssh/authorized_keys"

    # Dropbear authorized_keys dosyasını root ev dizininden okur.
    if [ -f /var/passwd ]; then
        /bin/sed -i 's|^\(root:[^:]*:0:0:[^:]*:\)[^:]*:\(.*\)$|\1/var/run/misc/misc_rw/root-home:\2|' /var/passwd
    fi

    while /usr/bin/iptables -D INPUT -i br0 -p tcp --dport 2222 -j ACCEPT 2>/dev/null; do :; done
    while /usr/bin/iptables -D INPUT -p tcp --dport 2222 -j DROP 2>/dev/null; do :; done
    /usr/bin/iptables -I INPUT 1 -p tcp --dport 2222 -j DROP
    /usr/bin/iptables -I INPUT 1 -i br0 -p tcp --dport 2222 -j ACCEPT

    if [ -s "$ssh_pid" ] && /bin/kill -0 "$(/bin/cat "$ssh_pid")" 2>/dev/null; then
        return
    fi
    /bin/rm -f "$ssh_pid"
    "$sshd" -p 2222 -P "$ssh_pid" -r "$host_key" \
        >/var/tmp/ex520-dropbear.log 2>&1
}

install_service() {
cat >"$login_script" <<'LOGIN'
#!/bin/sh
echo 'username:'
IFS= read -r supplied_user
if [ "$supplied_user" != 'root' ]; then
    echo 'Access denied'
    exit 1
fi
unset supplied_user
echo 'password:'
IFS= read -r supplied
if [ "$supplied" != '__ROOT_PASSWORD__' ]; then
    echo 'Access denied'
    exit 1
fi
unset supplied
exec /bin/sh
LOGIN
    chmod 700 "$login_script"

    /usr/bin/iptables -C INPUT -p tcp --dport 2323 -j DROP 2>/dev/null || \
        /usr/bin/iptables -I INPUT 1 -p tcp --dport 2323 -j DROP
    while /usr/bin/iptables -D INPUT -p tcp -s 192.168.0.0/24 --dport 2323 -j ACCEPT 2>/dev/null; do :; done
    while /usr/bin/iptables -D INPUT -p tcp -s 192.168.1.0/24 --dport 2323 -j ACCEPT 2>/dev/null; do :; done
    /usr/bin/iptables -C INPUT -i br0 -p tcp --dport 2323 -j ACCEPT 2>/dev/null || \
        /usr/bin/iptables -I INPUT 1 -i br0 -p tcp --dport 2323 -j ACCEPT

    if ! /bin/netstat -ltn 2>/dev/null | /bin/grep -q ':2323 '; then
        /usr/sbin/telnetd -p 2323 -l "$login_script" 2>/dev/null || true
    fi
}

# Sonradan başlayan servisler değiştirirse kuralları yeniden uygula.
while true; do
    restore_feature_traffic
    install_agent_compat
    install_panel_root_account
    install_admin_root_role
    restore_stock_webroot
    install_stock_page_visibility
    install_stock_menu_unlock
    install_root_api
    install_ssh
    install_tr069_lockdown
    install_wan_management_lockdown
    install_service
    sleep 15
done
