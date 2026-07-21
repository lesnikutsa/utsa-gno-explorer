import json
import struct
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = REPOSITORY_ROOT / "frontend" / "public"
ASSETS_DIR = PUBLIC_DIR / "assets"
INDEX_HTML = REPOSITORY_ROOT / "frontend" / "index.html"

FAVICON_FILES = (
    "favicon.ico",
    "favicon-16x16.png",
    "favicon-32x32.png",
    "apple-touch-icon.png",
    "android-chrome-192x192.png",
    "android-chrome-512x512.png",
    "site.webmanifest",
)

PNG_DIMENSIONS = {
    "favicon-16x16.png": (16, 16),
    "favicon-32x32.png": (32, 32),
    "apple-touch-icon.png": (180, 180),
    "android-chrome-192x192.png": (192, 192),
    "android-chrome-512x512.png": (512, 512),
}


def read_png_dimensions(path):
    with path.open("rb") as image:
        header = image.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError(f"Invalid PNG IHDR header: {path}")
    return struct.unpack(">II", header[16:24])


def read_ico_dimensions(path):
    with path.open("rb") as icon:
        header = icon.read(6)
        if len(header) != 6:
            raise ValueError(f"Invalid ICO header: {path}")
        reserved, image_type, image_count = struct.unpack("<HHH", header)
        if reserved != 0 or image_type != 1:
            raise ValueError(f"Invalid ICO directory: {path}")
        entries = icon.read(image_count * 16)
    if len(entries) != image_count * 16:
        raise ValueError(f"Truncated ICO directory: {path}")
    return {
        (entries[offset] or 256, entries[offset + 1] or 256)
        for offset in range(0, len(entries), 16)
    }


class FrontendFaviconAssetsTests(unittest.TestCase):
    def test_favicon_files_are_in_public_root_only(self):
        for name in FAVICON_FILES:
            with self.subTest(name=name):
                self.assertTrue((PUBLIC_DIR / name).is_file())
                self.assertFalse((ASSETS_DIR / name).exists())

    def test_png_dimensions(self):
        for name, dimensions in PNG_DIMENSIONS.items():
            with self.subTest(name=name):
                self.assertEqual(read_png_dimensions(PUBLIC_DIR / name), dimensions)

    def test_ico_contains_required_dimensions(self):
        dimensions = read_ico_dimensions(PUBLIC_DIR / "favicon.ico")
        self.assertTrue({(16, 16), (32, 32), (48, 48)}.issubset(dimensions))

    def test_manifest(self):
        manifest_path = PUBLIC_DIR / "site.webmanifest"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertTrue(manifest_path.read_bytes().endswith(b"\n"))
        self.assertEqual(manifest["name"], "UTSA Gno.land Explorer")
        self.assertEqual(manifest["short_name"], "Gno Explorer")
        self.assertEqual(manifest["background_color"], "#071827")
        self.assertEqual(manifest["theme_color"], "#071827")
        icon_paths = {icon["src"] for icon in manifest["icons"]}
        self.assertIn("/android-chrome-192x192.png", icon_paths)
        self.assertIn("/android-chrome-512x512.png", icon_paths)

    def test_index_references_favicon_assets_and_theme(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        for path in (
            "/favicon.ico",
            "/favicon-16x16.png",
            "/favicon-32x32.png",
            "/apple-touch-icon.png",
            "/site.webmanifest",
        ):
            with self.subTest(path=path):
                self.assertIn(path, html)
        self.assertIn('<meta name="theme-color" content="#071827" />', html)

    def test_sidebar_logo_is_unchanged(self):
        self.assertTrue((ASSETS_DIR / "utsa-logo.png").is_file())
        component = (REPOSITORY_ROOT / "frontend" / "src" / "components" / "UtsaLogo.jsx")
        self.assertIn("/assets/utsa-logo.png", component.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
