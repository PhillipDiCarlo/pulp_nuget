Syncs are now skipped when nothing changed since the last one: the remote's
configuration and the upstream registration index checksums are recorded on the
repository (``last_sync_details``), and an unchanged resync short-circuits with a
``sync.was_skipped`` progress report. Pass ``optimize=false`` to the sync call to
force a full pass.
