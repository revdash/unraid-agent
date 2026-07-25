#!/bin/bash
# unraid-agent installer
#
# Run this ON YOUR UNRAID SERVER (as root, via the Tower terminal or
# SSH). It sets up everything the agent needs:
#   1. A dedicated non-root SSH user for the agent
#   2. An SSH key pair for that user
#   3. sshd configured to allow that user (persisted across reboots)
#   4. A locked-down Docker socket proxy (read + start/stop/restart
#      only -- DELETE/PUT hard-blocked, cannot be reopened by config)
#   5. A .env file wired up with everything above
#
# Safe to re-run -- each step checks whether it's already done.

set -e

AGENT_USER="${AGENT_USER:-ai-agent}"
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KEY_PATH="/root/.ssh/${AGENT_USER}_key"
DOCKER_PROXY_PORT="${DOCKER_PROXY_PORT:-2375}"

# sshd on Unraid typically binds to the LAN IP, not loopback -- using
# 127.0.0.1 for the connectivity check below will falsely fail even
# when SSH is working fine. Auto-detection can also pick a Docker
# bridge IP instead of the real LAN IP on hosts with many virtual
# networks, so always confirm with the user rather than trusting it.
DETECTED_IP=$(ip route get 1 2>/dev/null | awk '{print $7; exit}')
echo "Detected LAN IP: ${DETECTED_IP:-none found}"
read -rp "Press enter to use this, or type the correct LAN IP for this server: " IP_INPUT
HOST_IP="${IP_INPUT:-$DETECTED_IP}"
if [ -z "$HOST_IP" ]; then
  echo "No IP provided, cannot continue."
  exit 1
fi

echo "== unraid-agent installer =="
echo "Install directory: $INSTALL_DIR"
echo "Using host IP: $HOST_IP"
echo

# --- 1. Create the dedicated user ---
if id "$AGENT_USER" &>/dev/null; then
  echo "[1/6] User '$AGENT_USER' already exists, skipping."
else
  echo "[1/6] Creating user '$AGENT_USER'..."
  useradd -m -s /bin/bash "$AGENT_USER"
  echo "Set a password for $AGENT_USER (needed once, for the initial key copy):"
  passwd "$AGENT_USER"
fi

# --- 2. SSH key pair ---
if [ -f "$KEY_PATH" ]; then
  echo "[2/6] SSH key already exists at $KEY_PATH, skipping."
else
  echo "[2/6] Generating SSH key pair..."
  ssh-keygen -t ed25519 -f "$KEY_PATH" -N "" -q
fi

if ! ssh -o BatchMode=yes -o ConnectTimeout=3 -i "$KEY_PATH" \
     "${AGENT_USER}@${HOST_IP}" true 2>/dev/null; then
  echo "Copying key to $AGENT_USER's authorized_keys (enter the password from step 1 if prompted)..."
  ssh-copy-id -o StrictHostKeyChecking=no -i "${KEY_PATH}.pub" "${AGENT_USER}@${HOST_IP}" || {
    echo "[warn] ssh-copy-id failed. If SSH isn't enabled yet, turn it on in"
    echo "       Settings -> Management Access, then re-run this script."
  }
fi

# --- 3. sshd AllowUsers + persistence ---
echo "[3/6] Checking sshd_config..."
if grep -q "^AllowUsers" /etc/ssh/sshd_config; then
  if ! grep "^AllowUsers" /etc/ssh/sshd_config | grep -q "$AGENT_USER"; then
    sed -i "s/^AllowUsers.*/& $AGENT_USER/" /etc/ssh/sshd_config
    /etc/rc.d/rc.sshd restart
    echo "Added $AGENT_USER to AllowUsers and restarted sshd."
  else
    echo "$AGENT_USER already in AllowUsers, skipping."
  fi
else
  echo "No AllowUsers restriction found in sshd_config -- all users already allowed, skipping."
fi

if ! grep -q "$AGENT_USER" /boot/config/go 2>/dev/null; then
  cat >> /boot/config/go << EOF

# --- $AGENT_USER SSH persistence (added by unraid-agent installer) ---
sleep 5
if ! grep -q "$AGENT_USER" /etc/ssh/sshd_config; then
  sed -i "s/^AllowUsers root/AllowUsers root $AGENT_USER/" /etc/ssh/sshd_config
fi
/etc/rc.d/rc.sshd restart
EOF
  echo "Persisted sshd config change to /boot/config/go (survives reboot)."
fi

# --- 4. Remove agent user from docker group if present (real isolation
#     comes from the proxy, not group membership) ---
echo "[4/6] Ensuring $AGENT_USER has no direct Docker socket access..."
gpasswd -d "$AGENT_USER" docker 2>/dev/null || true

# --- 5. Docker socket proxy ---
if docker ps --format '{{.Names}}' | grep -q "^${AGENT_USER}-docker-proxy$"; then
  echo "[5/6] Docker proxy already running, skipping."
elif docker ps --format '{{.Ports}}' | grep -q "127.0.0.1:${DOCKER_PROXY_PORT}->"; then
  echo "[5/6] Port $DOCKER_PROXY_PORT is already in use by another container on this host."
  echo "      Set DOCKER_PROXY_PORT to a free port and re-run, e.g.:"
  echo "        DOCKER_PROXY_PORT=2380 ./install.sh"
  exit 1
else
  echo "[5/6] Deploying locked-down Docker socket proxy..."
  docker run -d --name "${AGENT_USER}-docker-proxy" --restart unless-stopped \
    -p "127.0.0.1:${DOCKER_PROXY_PORT}:2375" \
    -v /var/run/docker.sock:/var/run/docker.sock:ro \
    -v "$INSTALL_DIR/haproxy.cfg.template:/usr/local/etc/haproxy/haproxy.cfg.template:ro" \
    tecnativa/docker-socket-proxy
  echo "Proxy running on 127.0.0.1:${DOCKER_PROXY_PORT} (read + start/stop/restart only; DELETE/PUT hard-blocked)."
fi

# --- 6. .env file ---
if [ -f "$INSTALL_DIR/.env" ]; then
  echo "[6/6] .env already exists, leaving it alone."
else
  echo "[6/6] Writing .env..."
  cp "$INSTALL_DIR/env.example" "$INSTALL_DIR/.env"
  sed -i "s|^UNRAID_HOST=.*|UNRAID_HOST=${HOST_IP}|" "$INSTALL_DIR/.env"
  sed -i "s|^SSH_KEY_PATH=.*|SSH_KEY_PATH=$KEY_PATH|" "$INSTALL_DIR/.env"
  sed -i "s|^UNRAID_USER=.*|UNRAID_USER=$AGENT_USER|" "$INSTALL_DIR/.env"
  sed -i "s|^DOCKER_PROXY_PORT=.*|DOCKER_PROXY_PORT=${DOCKER_PROXY_PORT}|" "$INSTALL_DIR/.env"
  chmod 600 "$INSTALL_DIR/.env"
  echo "Wrote $INSTALL_DIR/.env (detected host IP: ${HOST_IP:-not detected, please edit manually})."
fi

echo
echo "== Done =="
echo "Review $INSTALL_DIR/.env, then run:"
echo "  cd $INSTALL_DIR && ./agent.sh healthcheck"
