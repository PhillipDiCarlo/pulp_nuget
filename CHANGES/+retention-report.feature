Tasks that create a repository version now carry a ``retention.trimmed`` progress
report when ``retain_package_versions`` removed content, so an added version that was
dropped again for being older than the retained ones no longer disappears silently.
