"""Sphinx configuration.

To learn more about the Sphinx configuration for technotes, and how to
customize it, see:

https://documenteer.lsst.io/technotes/configuration.html
"""

from documenteer.conf.technote import *  # noqa: F401, F403

# Allow references to Python functions to be turned into links.
intersphinx_mapping = {
    "python": ("https://docs.python.org/3/", None),
}
