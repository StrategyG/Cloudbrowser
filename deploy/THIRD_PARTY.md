`seccomp_profile.json` is adapted from Microsoft Playwright v1.64.1:
https://github.com/microsoft/playwright/blob/v1.64.1/utils/docker/seccomp_profile.json

Copyright Microsoft Corporation. Licensed under Apache License 2.0;
see `Playwright-Apache-2.0.txt` in this directory.

Adaptation: return ENOSYS for clone3, allowing modern libc to fall back to clone;
the upstream policy allows the user namespaces needed for Chromium's sandbox.
Allow the chroot syscall without a Docker capability predicate: Chromium needs it
inside its newly created user namespace, while the container drops all outer
capabilities. Linux still enforces the caller's namespace capability checks.
No SYS_ADMIN capability, privileged container or unconfined seccomp mode is requested.
