# Fermentor reboot control

Home Assistant exposes `script.reboot_fermentor` for the confirmation-protected
dashboard button. The script calls `shell_command.reboot_fermentor`, which uses
an SSH host alias so no fermentor address, username, or private key is committed
to this repository.

## Home Assistant setup

The preferred flow is to generate the dedicated key on Home Assistant, where
the private key will be used:

```sh
mkdir -p /config/.ssh
chmod 700 /config/.ssh
ssh-keygen -t ed25519 -N '' \
  -C home-assistant-fermentor-reboot \
  -f /config/.ssh/fermentor_reboot_ed25519
ssh-keyscan -H <fermentor-address> >> /config/.ssh/known_hosts
chmod 600 /config/.ssh/fermentor_reboot_ed25519
chmod 644 /config/.ssh/fermentor_reboot_ed25519.pub /config/.ssh/known_hosts
```

Copy the single line from
`/config/.ssh/fermentor_reboot_ed25519.pub` into the restricted fermentor
account's `~/.ssh/authorized_keys` as described below. Never copy the private
key into `authorized_keys`.

If the dedicated key pair was instead generated on fermentor, copy only its
private half to Home Assistant and remove that private half from fermentor as
soon as the transfer succeeds:

```sh
# Run on fermentor. Replace <ha-ssh-user> and <ha-address>.
scp ./fermentor_reboot_ed25519 \
  <ha-ssh-user>@<ha-address>:/config/.ssh/fermentor_reboot_ed25519
ssh <ha-ssh-user>@<ha-address> \
  'chmod 600 /config/.ssh/fermentor_reboot_ed25519'
shred -u ./fermentor_reboot_ed25519
```

Keep `fermentor_reboot_ed25519.pub` on fermentor for the `authorized_keys`
entry. If the Home Assistant SSH app does not expose `/config` to SCP, copy the
file to that app's home directory first, then move it into `/config/.ssh` from
the Home Assistant terminal.

Create `/config/.ssh/config` in the Home Assistant Core filesystem:

```sshconfig
Host fermentor
  HostName <fermentor-address>
  User <restricted-user>
  IdentityFile /config/.ssh/fermentor_reboot_ed25519
  IdentitiesOnly yes
  UserKnownHostsFile /config/.ssh/known_hosts
```

Install the private key at `/config/.ssh/fermentor_reboot_ed25519`, add
fermentor's host key to `/config/.ssh/known_hosts`, and use restrictive
permissions:

```sh
chmod 700 /config/.ssh
chmod 600 /config/.ssh/config /config/.ssh/fermentor_reboot_ed25519
chmod 644 /config/.ssh/known_hosts
```

The Home Assistant Core runtime must provide `/usr/bin/ssh`. Confirm that path
inside the Core container before reloading `shell_command`.

## Fermentor setup

Prefer a dedicated unprivileged account. Permit only the reboot command in a
sudoers drop-in, replacing `<restricted-user>` with the account from the SSH
config:

```sudoers
<restricted-user> ALL=(root) NOPASSWD: /usr/bin/systemctl reboot
```

For defense in depth, restrict the public key in that user's
`~/.ssh/authorized_keys` entry:

```text
restrict,command="sudo -n /usr/bin/systemctl reboot" ssh-ed25519 <public-key> home-assistant-fermentor-reboot
```

After the local files and remote authorization are ready, reload Shell Command
and Scripts, then test `script.reboot_fermentor` from Home Assistant's action
developer tool before using the dashboard button.
