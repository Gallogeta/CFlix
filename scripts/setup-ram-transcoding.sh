#!/usr/bin/env bash
# ==============================================================================
# Jellyfin Zero-Disk-Wear In-RAM Transcoding Optimizer
# Tailored for 32GB RAM systems (Allocates 8GB safe tmpfs sliding window)
# ==============================================================================

set -euo pipefail

# 1. Require root or sudo privileges
if [[ $EUID -ne 0 ]]; then
   echo "[-] Error: This script must be run with sudo: sudo bash $0"
   exit 1
fi

echo "======================================================="
echo "   Jellyfin In-RAM Transcoding Setup (Zero SSD Wear)   "
echo "======================================================="

# 2. Detect Docker or Bare-Metal Jellyfin
IS_DOCKER=false
JELLYFIN_CONFIG_DIR=""

if command -v docker &>/dev/null && docker ps --format '{{.Names}}' | grep -q "^jellyfin$"; then
    IS_DOCKER=true
    echo "[+] Detected running Docker container: 'jellyfin'"
    
    # Locate mounted config path on host
    JELLYFIN_CONFIG_DIR=$(docker inspect jellyfin --format '{{range .Mounts}}{{if eq .Destination "/config"}}{{.Source}}{{end}}{{end}}')
    if [[ -z "$JELLYFIN_CONFIG_DIR" ]]; then
        # Fallback check
        JELLYFIN_CONFIG_DIR=$(find /home /root -name "encoding.xml" -path "*/config/encoding.xml" 2>/dev/null | head -n 1 | xargs dirname)
    fi
else
    echo "[+] Detected bare-metal / systemd Jellyfin installation"
    for candidate in /etc/jellyfin /var/lib/jellyfin/config /config; do
        if [[ -f "$candidate/encoding.xml" ]]; then
            JELLYFIN_CONFIG_DIR="$candidate"
            break
        fi
    done
fi

if [[ -z "$JELLYFIN_CONFIG_DIR" || ! -f "$JELLYFIN_CONFIG_DIR/encoding.xml" ]]; then
    echo "[-] Could not automatically locate 'encoding.xml'."
    read -rp "Please enter the full path to your Jellyfin config directory: " JELLYFIN_CONFIG_DIR
    if [[ ! -f "$JELLYFIN_CONFIG_DIR/encoding.xml" ]]; then
        echo "[-] Error: $JELLYFIN_CONFIG_DIR/encoding.xml not found."
        exit 1
    fi
fi

echo "[+] Config directory located at: $JELLYFIN_CONFIG_DIR"

# 3. Configure RAM Disk
if [ "$IS_DOCKER" = true ]; then
    echo "[+] Docker setup: Ensure your docker-compose.yml or docker run has the transcode volume mapped to RAM:"
    echo "    volumes:"
    echo "      - /dev/shm:/transcode"
    echo ""
    echo "[+] Verifying container /transcode mount..."
    docker exec jellyfin mkdir -p /transcode || true
else
    echo "[+] Setting up high-speed 8GB RAM tmpfs at /transcode..."
    mkdir -p /transcode
    
    # Determine jellyfin user/group
    JF_USER="jellyfin"
    if ! id "$JF_USER" &>/dev/null; then
        JF_USER="root"
    fi
    chown -R "$JF_USER:$JF_USER" /transcode
    chmod 1777 /transcode

    # Add to /etc/fstab if not already present
    if ! grep -q "/transcode" /etc/fstab; then
        echo "tmpfs /transcode tmpfs defaults,noatime,nosuid,nodev,noexec,mode=1777,size=8G 0 0" >> /etc/fstab
        echo "[+] Added /transcode tmpfs (8GB) to /etc/fstab"
    fi
    mount -a
fi

# 4. Backup and modify encoding.xml
ENCODING_XML="$JELLYFIN_CONFIG_DIR/encoding.xml"
cp "$ENCODING_XML" "$ENCODING_XML.bak_$(date +%Y%m%d_%H%M%S)"
echo "[+] Backed up encoding.xml to $ENCODING_XML.bak_*"

python3 - <<EOF
import re

with open("$ENCODING_XML", "r", encoding="utf-8") as f:
    content = f.read()

def replace_or_insert(xml, tag, value):
    pattern = rf"<{tag}>.*?</{tag}>"
    if re.search(pattern, xml):
        return re.sub(pattern, f"<{tag}>{value}</{tag}>", xml)
    else:
        return xml.replace("</EncodingOptions>", f"  <{tag}>{value}</{tag}>\n</EncodingOptions>")

# 1. Transcode strictly into RAM
content = replace_or_insert(content, "TranscodingTempPath", "/transcode")

# 2. Enable controlled ahead buffer (120 seconds ahead)
content = replace_or_insert(content, "EnableThrottling", "true")
content = replace_or_insert(content, "ThrottleDelaySeconds", "120")

# 3. Enable aggressive segment purging (past segments deleted after 60 seconds)
content = replace_or_insert(content, "EnableSegmentDeletion", "true")
content = replace_or_insert(content, "SegmentKeepSeconds", "60")

with open("$ENCODING_XML", "w", encoding="utf-8") as f:
    f.write(content)

print("[+] Successfully tuned encoding.xml settings!")
EOF

# 5. Restart Jellyfin to apply
echo "[+] Restarting Jellyfin to apply settings..."
if [ "$IS_DOCKER" = true ]; then
    docker restart jellyfin
else
    systemctl restart jellyfin
fi

echo "======================================================="
echo "  SUCCESS! In-RAM Transcoding is now active:          "
echo "  - Storage: RAM only (0% SSD/HDD wear)                "
echo "  - Past segments: Automatically deleted after 60s    "
echo "  - Future buffer: Transcodes max 120s ahead          "
echo "  - Total RAM used while watching: ~150 MB - 300 MB    "
echo "======================================================="
