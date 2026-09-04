"""The cache-busting versions on the shared static files.

Every page carries its own `?v=` on the assets it links, and styles.css is linked by all
three. They drifted: the panel asked for v=106 while the sign-in and setup pages still
asked for v=4, so months of changes to the shared stylesheet reached the panel and never
reached the page a beekeeper signs in on — the browser kept serving whatever it had
cached under the old query. Nothing fails loudly when that happens, which is why it is
checked here instead.
"""

import re
import unittest
from collections import defaultdict
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
PAGES = ("index.html", "login.html", "setup.html")
ASSET = re.compile(r'/static/([A-Za-z0-9_.-]+)\?v=(\d+)')


class StaticAssetVersionTest(unittest.TestCase):
    def _versions(self) -> dict[str, dict[str, str]]:
        found: dict[str, dict[str, str]] = defaultdict(dict)
        for page in PAGES:
            for asset, version in ASSET.findall((STATIC / page).read_text(encoding="utf-8")):
                found[asset][page] = version
        return found

    def test_a_shared_asset_carries_one_version_everywhere(self):
        for asset, byPage in self._versions().items():
            with self.subTest(asset=asset):
                self.assertEqual(
                    len(set(byPage.values())), 1,
                    f"{asset} is requested at different versions: {dict(byPage)}",
                )

    def test_every_versioned_asset_exists(self):
        """A typo in the name is a silently unstyled page, not an error anyone sees."""
        for asset in self._versions():
            with self.subTest(asset=asset):
                self.assertTrue((STATIC / asset).is_file(), f"{asset} is linked but missing")
