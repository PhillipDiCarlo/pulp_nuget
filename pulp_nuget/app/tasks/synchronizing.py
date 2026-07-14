"""Sync a repository from an upstream NuGet v3 feed. (Implemented in a later phase.)"""

from gettext import gettext as _
import logging

log = logging.getLogger(__name__)


def synchronize(remote_pk, repository_pk, mirror):
    """
    Sync content from the remote repository.

    Args:
        remote_pk (str): The remote PK.
        repository_pk (str): The repository PK.
        mirror (bool): True for mirror mode, False for additive.
    """
    raise NotImplementedError(_("NuGet sync is not implemented yet."))
