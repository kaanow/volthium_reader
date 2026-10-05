# Interactive sessions on the barge Pi create group-writable files.
#
# WHY: /srv/volthium_reader/data is shared between the services (user
# `claude`) and the operator (user `kaan`) through the common group `users`.
# With the default umask 0022 a file created by either one comes out 0644 and
# the other can never append to it again.
#
# That is not hypothetical. On 2026-10-04 an operator SSH session recreated
# data/pack.csv as kaan:users 0644; the rs485 logger, running as claude, then
# crash-looped 593 times and left a 70.3-minute hole in the primary telemetry
# record at a site nobody visits for weeks.
#
# The services carry UMask=0002 in their unit files. This is the other half:
# without it, the next ad-hoc command run over SSH re-creates the same trap.
# Paired with the setgid bit on data/ (chmod g+s), which makes new files
# inherit group `users` instead of the writer's primary group.
umask 0002
