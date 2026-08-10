import logging
import sys
from importlib.metadata import version

logger = logging.getLogger(__name__)


def show_versions():
    """
    This function prints version information that is useful when filing bug
    reports.

    Examples
    --------
    Calling this function should print information like the following
    (dependency versions in your local installation will likely differ):

    >>> import setp_hgs_kernel
    >>> setp_hgs_kernel.show_versions()
    INSTALLED VERSIONS
    ------------------
         setp_hgs_kernel: 1.0.0
         numpy: 1.24.2
    matplotlib: 3.7.0
        vrplib: 1.0.1
          tqdm: 4.64.1
        Python: 3.9.13
    """
    python_version = ".".join(map(str, sys.version_info[:3]))

    logger.info("INSTALLED VERSIONS")
    logger.info("------------------")
    logger.info(f"     setp_hgs_kernel: {version('setp_hgs_kernel')}")
    logger.info(f"     numpy: {version('numpy')}")
    logger.info(f"matplotlib: {version('matplotlib')}")
    logger.info(f"    vrplib: {version('vrplib')}")
    logger.info(f"      tqdm: {version('tqdm')}")
    logger.info(f"    Python: {python_version}")
