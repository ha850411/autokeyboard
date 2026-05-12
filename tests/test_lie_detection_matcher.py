from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from autokeyboard import (
    ImageTemplateMatcher,
    LieDetectionMatcher,
    RECAPTCHA_MATCH_SCALE_STEP_RATIO,
    RECAPTCHA_TEMPLATE_PATH,
    build_recaptcha_match_scales,
)


FALSE_POSITIVE_DIR = ROOT / "tests" / "fixtures" / "lie_detection_false_positives"
TRUE_POSITIVE_DIR = ROOT / "tests" / "fixtures" / "lie_detection_true_positives"
LEGACY_TRUE_POSITIVE_DIR = ROOT / "tests" / "fixtures" / "lie_detection_legacy_true_positives"
IMAGE_EXTENSIONS = {".bmp", ".jpeg", ".jpg", ".png", ".webp"}


def fixture_images(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.casefold() in IMAGE_EXTENSIONS
    )


def maple_shop_like_screenshot() -> Image.Image:
    image = Image.new("RGB", (1366, 768), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((360, 175, 745, 315), radius=10, fill=(242, 242, 242), outline=(86, 86, 86), width=4)
    draw.rounded_rectangle((755, 175, 1135, 315), radius=10, fill=(242, 242, 242), outline=(86, 86, 86), width=4)
    draw.rounded_rectangle((625, 225, 730, 252), radius=6, fill=(32, 176, 220), outline=(106, 210, 240), width=2)
    draw.rounded_rectangle((625, 258, 730, 285), radius=6, fill=(245, 155, 18), outline=(255, 201, 65), width=2)
    draw.rounded_rectangle((1010, 244, 1116, 273), radius=6, fill=(245, 155, 18), outline=(255, 201, 65), width=2)

    for x in (385, 770):
        for y in range(360, 700, 70):
            draw.rectangle((x, y, x + 330, y + 55), fill=(226, 226, 226), outline=(148, 148, 148), width=2)
            draw.rectangle((x + 6, y + 6, x + 54, y + 49), fill=(245, 245, 245), outline=(190, 190, 190))
            draw.text((x + 68, y + 7), "item", fill=(25, 25, 25))
            draw.text((x + 68, y + 30), "37,400", fill=(25, 25, 25))

    return image


def maple_worlds_catalog_decoy_screenshot() -> Image.Image:
    image = Image.new("RGB", (1555, 921), (224, 224, 224))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((142, 23, 1550, 920), radius=34, fill=(250, 249, 247))
    draw.text((169, 122), "楓之谷世界1週年紀念慶典", fill=(35, 35, 35))
    draw.text((169, 371), "編輯精選", fill=(35, 35, 35))
    draw.text((169, 634), "最近遊玩的", fill=(35, 35, 35))

    template = Image.open(RECAPTCHA_TEMPLATE_PATH).convert("RGB")
    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    decoy = template.resize((200, 92), resample)
    decoy_draw = ImageDraw.Draw(decoy)
    decoy_draw.rectangle((0, 0, 199, 4), fill=(184, 48, 48))
    decoy_draw.rectangle((0, 5, 5, 91), fill=(31, 169, 91))
    decoy_draw.ellipse((160, 35, 195, 70), fill=(250, 201, 40))
    decoy_draw.text((64, 36), "雪吉拉", fill=(35, 35, 35))

    cards = [
        (170, 153, (39, 117, 169), "NexTale"),
        (390, 153, None, "P-Maple 雪吉拉伺服器"),
        (610, 153, (78, 175, 96), "ChronoStory"),
        (390, 418, None, "楓星"),
        (1050, 418, None, "P-Maple 雪吉拉伺服器"),
    ]
    for x, y, color, title in cards:
        draw.rounded_rectangle((x, y, x + 202, y + 175), radius=9, fill=(255, 255, 255), outline=(241, 241, 241))
        if color is None:
            image.paste(decoy, (x, y))
        else:
            draw.rectangle((x, y, x + 202, y + 92), fill=color)
            draw.text((x + 35, y + 35), title, fill=(255, 255, 255))
        draw.text((x + 42, y + 122), title, fill=(86, 86, 86))
        draw.text((x + 42, y + 145), "MapleStoryWorlds", fill=(160, 160, 160))

    return image


def screenshot_with_scaled_lie_detection(scale: float, *, checked: bool = False) -> Image.Image:
    canvas = Image.new("RGB", (1366, 768), (0, 0, 0))
    template = Image.open(RECAPTCHA_TEMPLATE_PATH).convert("RGB")
    if checked:
        draw = ImageDraw.Draw(template)
        draw.rounded_rectangle((26, 55, 68, 98), radius=5, outline=(48, 164, 154), width=4)
        draw.line((37, 76, 49, 88, 63, 63), fill=(48, 164, 154), width=4)
    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    scaled = template.resize((int(template.width * scale), int(template.height * scale)), resample)
    canvas.paste(scaled, (600, 220))
    return canvas


class LieDetectionMatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compact_matcher = ImageTemplateMatcher(RECAPTCHA_TEMPLATE_PATH)
        cls.matcher = LieDetectionMatcher(RECAPTCHA_TEMPLATE_PATH)

    def test_detects_current_lie_detection_template(self) -> None:
        image = Image.open(RECAPTCHA_TEMPLATE_PATH).convert("RGB")

        result = self.compact_matcher.analyze(image)

        self.assertTrue(result.matched)

    def test_detects_small_in_game_lie_detection_template(self) -> None:
        result = self.compact_matcher.analyze(screenshot_with_scaled_lie_detection(0.3))

        self.assertTrue(result.matched)

    def test_detects_high_dpi_scaled_lie_detection_template(self) -> None:
        result = self.compact_matcher.analyze(screenshot_with_scaled_lie_detection(1.5))

        self.assertTrue(result.matched)

    def test_detects_1080p_checked_lie_detection_template(self) -> None:
        result = self.compact_matcher.analyze(screenshot_with_scaled_lie_detection(0.8, checked=True))

        self.assertTrue(result.matched)

    def test_detects_lie_detection_between_manual_scale_points(self) -> None:
        for scale in (0.81, 0.97, 1.23):
            with self.subTest(scale=scale):
                result = self.compact_matcher.analyze(screenshot_with_scaled_lie_detection(scale, checked=True))

                self.assertTrue(result.matched)

    def test_generated_scale_candidates_do_not_leave_large_gaps(self) -> None:
        scales = build_recaptcha_match_scales()

        self.assertGreater(len(scales), 40)
        max_gap = max(next_scale / scale for scale, next_scale in zip(scales, scales[1:]))
        self.assertLessEqual(max_gap, RECAPTCHA_MATCH_SCALE_STEP_RATIO + 0.01)

    def test_maple_shop_like_ui_is_not_detected(self) -> None:
        result = self.matcher.analyze(maple_shop_like_screenshot())

        self.assertFalse(result.matched)

    def test_maple_worlds_catalog_card_decoy_is_not_detected(self) -> None:
        result = self.matcher.analyze(maple_worlds_catalog_decoy_screenshot())

        self.assertFalse(result.matched)

    def test_false_positive_fixture_images_are_not_detected(self) -> None:
        for image_path in fixture_images(FALSE_POSITIVE_DIR):
            with self.subTest(image=image_path.name):
                image = Image.open(image_path).convert("RGB")

                result = self.matcher.analyze(image)

                self.assertFalse(result.matched, f"{image_path} was detected as lie detection")

    def test_true_positive_fixture_images_are_detected(self) -> None:
        for image_path in fixture_images(TRUE_POSITIVE_DIR):
            with self.subTest(image=image_path.name):
                image = Image.open(image_path).convert("RGB")

                result = self.matcher.analyze(image)

                self.assertTrue(result.matched, f"{image_path} was not detected as lie detection")

    def test_legacy_true_positive_fixture_images_are_detected(self) -> None:
        for image_path in fixture_images(LEGACY_TRUE_POSITIVE_DIR):
            with self.subTest(image=image_path.name):
                image = Image.open(image_path).convert("RGB")

                result = self.matcher.analyze(image)

                self.assertTrue(result.matched, f"{image_path} was not detected as lie detection")


if __name__ == "__main__":
    unittest.main()
