#!/bin/sh
set -eu

readonly source_dir=/usr/lib/ex520-mode-root
readonly destination=/var/run/misc/misc_rw
readonly config="$destination/0x00300000"
readonly plain=/var/tmp/ex520-mode-config.xml

is_agent_or_ap() {
    [ -s "$config" ] || return 2
    /bin/dd if="$config" bs=1 skip=16 2>/dev/null |
        /usr/sbin/openssl enc -d -aes-128-cbc \
            -K "$(/bin/cat "$source_dir/config-key.hex")" \
            -iv "$(/bin/cat "$source_dir/config-iv.hex")" \
            >"$plain" 2>/dev/null || return 2

    if /bin/grep -Eq '<Mode val="?AP"? />' "$plain" ||
       /bin/grep -Eq '<WorkMode val="?UnConfAgent"? />' "$plain" ||
       /bin/grep -Eq '<WorkMode val="?ConfAgent"? />' "$plain"; then
        /bin/rm -f "$plain"
        return 0
    fi
    /bin/rm -f "$plain"
    return 1
}

# cos/dmclid veri modelini hazırlayana kadar bekle. Router/Controller sonucu
# kesinleşirse hiçbir dosyaya dokunmadan çık.
attempt=0
while [ "$attempt" -lt 120 ]; do
    if is_agent_or_ap; then
        break
    fi
    result=$?
    [ "$result" -eq 1 ] && exit 0
    attempt=$((attempt + 1))
    /bin/sleep 1
done
[ "$attempt" -lt 120 ] || exit 0

install_asset() {
    name=$1
    mode=$2
    temporary="$destination/$name.mode-restore"

    /bin/cp "$source_dir/$name" "$temporary"
    /bin/chmod "$mode" "$temporary"
    /bin/mv "$temporary" "$destination/$name"
}

install_asset persistent-local-root.sh 700
install_asset ex520-root-api 700
install_asset ex520-dropbear 700
install_asset ex520-web-root-init 700
install_asset root-authorized-keys 600
install_asset root-api.token 600
install_asset release.version 600

/bin/sh "$destination/persistent-local-root.sh"
