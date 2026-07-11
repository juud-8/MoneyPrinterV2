import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from archived_brands import (  # noqa: E402
    ARCHIVED_BRANDS,
    BrandArchivedError,
    assert_brand_runnable,
    is_brand_archived,
)


class ArchivedBrandsTests(unittest.TestCase):
    def test_sixty_second_thrillers_is_archived(self) -> None:
        self.assertIn("sixty_second_thrillers", ARCHIVED_BRANDS)
        self.assertTrue(is_brand_archived("sixty_second_thrillers"))

    def test_active_brand_not_archived(self) -> None:
        self.assertFalse(is_brand_archived("the_strange_archive"))

    def test_assert_brand_runnable_raises(self) -> None:
        with self.assertRaises(BrandArchivedError):
            assert_brand_runnable("sixty_second_thrillers")


if __name__ == "__main__":
    unittest.main()
