# The three places umask has to be right, and why one is not enough

On 2026-10-04 the primary RS485 telemetry logger crash-looped **593 times over
70 minutes** and `data/pack.csv` froze between 03:16:39Z and 04:26:59Z:

```
PermissionError: [Errno 13] Permission denied: 'data/pack.csv'
```

Cause: an ad-hoc command run over SSH as `kaan` recreated `pack.csv`, and with
the default umask 0022 it came back `kaan:users 0644`. The services run as
`claude`. They share the group `users` precisely so the two can maintain the
same files — but 0644 is not group-writable, so the group was decorative and
`claude` could never append again.

Fixing this needs all three of the following. Each covers a case the others
miss, which is why the obvious single fix kept leaving the trap armed:

| # | Mechanism | Covers | Does NOT cover |
|---|-----------|--------|----------------|
| 1 | `UMask=0002` in the unit files | files the **services** create | anything the operator creates |
| 2 | `umask 0002` in `/etc/profile.d/volthium-umask.sh` | **login** shells | `ssh host 'cmd'` — profile.d is only read by login shells |
| 3 | `umask 0002` at the TOP of `~kaan/.bashrc` | **non-interactive** `ssh host 'cmd'` | — |

Plus `chmod g+s /srv/volthium_reader/data`, which makes new files inherit the
group `users` rather than the writer's primary group. Mode comes from umask;
group comes from setgid. Both are required.

**#3 is the one that actually mattered**, because `ssh host 'cmd'` is how this
repo is deployed and diagnosed, and it is a non-interactive, non-login shell.
I verified #2 alone was insufficient by probing it directly after installing
it — a login shell reported `0002` while `ssh kwpi 'touch …'` still produced
`0644`. bash does source `~/.bashrc` for remote commands (it detects
`SSH_CLIENT`), so the line must sit **above** the stock

```sh
# If not running interactively, don't do anything
case $- in
```

guard, or it is skipped in exactly the case it exists for.

`~/.bashrc` is not in this repo (it is a user dotfile on the Pi); the live copy
has the snippet at the top with a backup at `~/.bashrc.pre-umask`.

## Verifying it, rather than trusting it

Prevention that nothing checks is how several invariants in this codebase
decayed into permanently-green checks. `status_check.py --with-pi` now has a
`data perms` line that asserts the **property** — every file in `data/` is
group-writable — instead of trusting the three mechanisms above:

```
data perms      all 16 data file(s) group-writable — services can append
```

Root-owned files are listed but do not page: the xanbus capture and latch
guard run as root and own their state by design, and `chmod g+w` would not
help when the group is `root`.
