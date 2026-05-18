from __future__ import annotations

import io
import queue
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import autokeyboard as ak


class KeyResolverTests(unittest.TestCase):
    def test_normalizes_tokens_and_step_actions(self) -> None:
        self.assertEqual(ak.normalize_token(" ctrl_key "), "CTRLKEY")
        self.assertEqual(ak.normalize_step_action("wait"), ak.ACTION_DELAY)
        self.assertEqual(ak.normalize_step_action("按下按鍵"), ak.ACTION_KEY_DOWN)
        self.assertEqual(ak.normalize_step_action("放開按鍵"), ak.ACTION_KEY_UP)
        self.assertEqual(ak.normalize_step_action("呼叫腳本"), ak.ACTION_SCRIPT_CALL)
        self.assertEqual(ak.normalize_step_action("unknown"), ak.ACTION_KEY_DOWN)

    def test_resolves_named_keys_and_combinations(self) -> None:
        self.assertEqual(ak.KeyResolver.resolve_key_action("space"), ak.KeyAction(ak.VK_SPACE))
        self.assertEqual(
            ak.KeyResolver.resolve_key_action("CTRL+SHIFT+A"),
            ak.KeyAction(ord("A"), (ak.VK_CONTROL, ak.VK_SHIFT)),
        )
        self.assertEqual(
            ak.KeyResolver.resolve_key_action("CTRL+CTRL+A"),
            ak.KeyAction(ord("A"), (ak.VK_CONTROL,)),
        )

    def test_resolves_multiple_key_actions(self) -> None:
        actions = ak.KeyResolver.resolve_key_actions("X, SPACE, F8")

        self.assertEqual(actions, [ak.KeyAction(ord("X")), ak.KeyAction(ak.VK_SPACE), ak.KeyAction(0x77)])

    def test_parse_hotkey_returns_modifier_flags_and_vk(self) -> None:
        flags, vk = ak.KeyResolver.parse_hotkey("CTRL+ALT+F9")

        self.assertEqual(flags, ak.MOD_CONTROL | ak.MOD_ALT)
        self.assertEqual(vk, 0x78)

    def test_rejects_invalid_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "請輸入按鍵"):
            ak.KeyResolver.resolve_key_action("")
        with self.assertRaisesRegex(ValueError, "多按鍵請用逗號分隔"):
            ak.KeyResolver.resolve_key_actions("A,")
        with self.assertRaisesRegex(ValueError, "組合鍵只能"):
            ak.KeyResolver.resolve_key_action("A+CTRL")
        with self.assertRaisesRegex(ValueError, "快捷鍵需要包含一般按鍵"):
            ak.KeyResolver.parse_hotkey("CTRL")

    def test_unique_helpers_preserve_order(self) -> None:
        self.assertEqual(ak.unique_preserve_order([1, 2, 1, 3, 2]), (1, 2, 3))
        actions = [ak.KeyAction(1), ak.KeyAction(2), ak.KeyAction(1)]

        self.assertEqual(ak.unique_key_actions(actions), [ak.KeyAction(1), ak.KeyAction(2)])


class ScriptSerializationTests(unittest.TestCase):
    def test_legacy_step_dict_expands_to_down_delay_up_and_wait(self) -> None:
        steps = ak.Step.from_dicts({"key": "A", "press_ms": 250, "wait_ms": 500})

        self.assertEqual(
            steps,
            [
                ak.Step(ak.ACTION_KEY_DOWN, key="A"),
                ak.Step(ak.ACTION_DELAY, delay_ms=250),
                ak.Step(ak.ACTION_KEY_UP, key="A"),
                ak.Step(ak.ACTION_DELAY, delay_ms=500),
            ],
        )

    def test_step_round_trip_and_display_helpers(self) -> None:
        delay = ak.Step.from_dicts({"kind": "延遲", "ms": 1200})[0]
        key_up = ak.Step.from_dicts({"action": "keyup", "key": "SPACE"})[0]
        script_call = ak.Step.from_dicts({"action": "script_call", "script_id": "helper"})[0]

        self.assertEqual(delay.to_dict(), {"action": ak.ACTION_DELAY, "delay_ms": 1200})
        self.assertEqual(key_up.to_dict(), {"action": ak.ACTION_KEY_UP, "key": "SPACE"})
        self.assertEqual(script_call.to_dict(), {"action": ak.ACTION_SCRIPT_CALL, "script_id": "helper"})
        self.assertFalse(delay.needs_key())
        self.assertTrue(key_up.needs_key())
        self.assertTrue(script_call.needs_script())
        self.assertEqual(key_up.display_action(), "放開按鍵↑")
        self.assertEqual(script_call.display_action(), "呼叫腳本")

    def test_script_from_dict_uses_defaults_and_round_trips(self) -> None:
        script = ak.Script.from_dict(
            {
                "id": "script-1",
                "name": "測試腳本",
                "hotkey": "F8",
                "repeat": False,
                "steps": [{"action": "keydown", "key": "A"}, {"action": "delay", "delay_ms": 50}],
            }
        )

        self.assertEqual(script.id, "script-1")
        self.assertEqual(script.name, "測試腳本")
        self.assertFalse(script.repeat)
        self.assertEqual(script.to_dict()["steps"][0], {"action": ak.ACTION_KEY_DOWN, "key": "A"})

        clone = script.clone()
        clone.steps[0].key = "B"
        self.assertEqual(script.steps[0].key, "A")

    def test_default_script_is_usable(self) -> None:
        scripts = ak.default_scripts()

        self.assertEqual(len(scripts), 1)
        self.assertEqual(scripts[0].hotkey, "F8")
        self.assertGreaterEqual(len(scripts[0].steps), 4)


class ConfigPersistenceTests(unittest.TestCase):
    def test_save_and_load_scripts_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "scripts.json"
            legacy_path = Path(directory) / "legacy.json"
            scripts = [
                ak.Script(
                    id="script-1",
                    name="保存測試",
                    hotkey="CTRL+F8",
                    repeat=False,
                    steps=[ak.Step(ak.ACTION_KEY_DOWN, key="A"), ak.Step(ak.ACTION_KEY_UP, key="A")],
                )
            ]

            with patch.object(ak, "CONFIG_PATH", config_path), patch.object(ak, "LEGACY_CONFIG_PATH", legacy_path):
                ak.save_scripts(scripts)
                loaded = ak.load_scripts()

        self.assertEqual([script.to_dict() for script in loaded], [script.to_dict() for script in scripts])

    def test_save_and_load_script_groups_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "scripts.json"
            legacy_path = Path(directory) / "legacy.json"
            group_one = ak.ScriptGroup(
                id="group-1",
                name="角色 A",
                scripts=[ak.Script(id="script-a", name="A 腳本", steps=[ak.Step(ak.ACTION_DELAY, delay_ms=10)])],
            )
            group_two = ak.ScriptGroup(
                id="group-2",
                name="角色 B",
                scripts=[ak.Script(id="script-b", name="B 腳本", steps=[ak.Step(ak.ACTION_DELAY, delay_ms=20)])],
            )

            with patch.object(ak, "CONFIG_PATH", config_path), patch.object(ak, "LEGACY_CONFIG_PATH", legacy_path):
                ak.save_script_groups([group_one, group_two], group_two.id)
                groups, active_group_id = ak.load_script_groups()
                legacy_scripts = ak.load_scripts()
                saved_data = ak.json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(active_group_id, "group-2")
        self.assertEqual([group.name for group in groups], ["角色 A", "角色 B"])
        self.assertEqual(groups[1].scripts[0].name, "B 腳本")
        self.assertEqual([script.name for script in legacy_scripts], ["B 腳本"])
        self.assertEqual(saved_data["scripts"], [group_two.scripts[0].to_dict()])

    def test_load_script_groups_wraps_legacy_scripts_into_default_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "scripts.json"
            legacy_path = Path(directory) / "legacy.json"
            legacy_script = ak.Script(id="legacy", name="舊腳本", steps=[ak.Step(ak.ACTION_DELAY, delay_ms=10)])
            config_path.write_text(
                ak.json.dumps({"scripts": [legacy_script.to_dict()]}, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(ak, "CONFIG_PATH", config_path), patch.object(ak, "LEGACY_CONFIG_PATH", legacy_path):
                groups, active_group_id = ak.load_script_groups()

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].name, ak.DEFAULT_SCRIPT_GROUP_NAME)
        self.assertEqual(groups[0].id, active_group_id)
        self.assertEqual(groups[0].scripts[0].to_dict(), legacy_script.to_dict())

    def test_load_scripts_copies_legacy_config_when_user_config_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "user" / "scripts.json"
            legacy_path = Path(directory) / "legacy_scripts.json"
            legacy_script = ak.Script(id="legacy", name="舊設定", steps=[ak.Step(ak.ACTION_DELAY, delay_ms=10)])
            legacy_path.write_text(
                ak.json.dumps({"scripts": [legacy_script.to_dict()]}, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(ak, "CONFIG_PATH", config_path), patch.object(ak, "LEGACY_CONFIG_PATH", legacy_path):
                loaded = ak.load_scripts()
                copied = config_path.exists()

        self.assertTrue(copied)
        self.assertEqual(loaded[0].to_dict(), legacy_script.to_dict())

    def test_load_scripts_falls_back_to_default_on_invalid_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "scripts.json"
            legacy_path = Path(directory) / "legacy.json"
            config_path.write_text("{not json", encoding="utf-8")

            with (
                patch.object(ak, "CONFIG_PATH", config_path),
                patch.object(ak, "LEGACY_CONFIG_PATH", legacy_path),
                patch.object(ak.messagebox, "showwarning"),
            ):
                loaded = ak.load_scripts()

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].hotkey, "F8")

    def test_load_scripts_returns_default_when_no_config_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "missing" / "scripts.json"
            legacy_path = Path(directory) / "missing_legacy.json"

            with patch.object(ak, "CONFIG_PATH", config_path), patch.object(ak, "LEGACY_CONFIG_PATH", legacy_path):
                loaded = ak.load_scripts()

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].hotkey, "F8")

    def test_recaptcha_monitor_settings_round_trip_and_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "monitor.json"

            with patch.object(ak, "MONITOR_CONFIG_PATH", settings_path):
                self.assertEqual(ak.load_recaptcha_monitor_settings(), ak.RecaptchaMonitorSettings())

                ak.save_recaptcha_monitor_settings(
                    ak.RecaptchaMonitorSettings(
                        enabled=False,
                        recipient_name="羅總",
                        only_maplestory_window=False,
                    )
                )
                loaded = ak.load_recaptcha_monitor_settings()
                saved_data = ak.json.loads(settings_path.read_text(encoding="utf-8"))

                legacy_recipient = ak.DISCORD_RECIPIENTS_BY_NAME["蔡董"]
                settings_path.write_text(
                    ak.json.dumps(
                        {
                            "enabled": True,
                            "user_id": f"abc{legacy_recipient.user_id}",
                            "webhook_url": legacy_recipient.webhook_url,
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                legacy_loaded = ak.load_recaptcha_monitor_settings()

        self.assertEqual(
            loaded,
            ak.RecaptchaMonitorSettings(
                enabled=False,
                recipient_name="羅總",
                only_maplestory_window=False,
            ),
        )
        self.assertEqual(saved_data, {"enabled": False, "recipient_name": "羅總", "only_maplestory_window": False})
        self.assertEqual(
            legacy_loaded,
            ak.RecaptchaMonitorSettings(enabled=True, recipient_name="蔡董", only_maplestory_window=True),
        )

    def test_recaptcha_monitor_settings_invalid_config_returns_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "monitor.json"
            settings_path.write_text("{not json", encoding="utf-8")

            with patch.object(ak, "MONITOR_CONFIG_PATH", settings_path):
                loaded = ak.load_recaptcha_monitor_settings()

        self.assertEqual(loaded, ak.RecaptchaMonitorSettings())

    def test_running_overlay_settings_round_trip_and_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "running_overlay.json"

            with patch.object(ak, "RUNNING_OVERLAY_CONFIG_PATH", settings_path):
                self.assertEqual(ak.load_running_overlay_settings(), ak.RunningOverlaySettings())

                ak.save_running_overlay_settings(ak.RunningOverlaySettings(enabled=False, opacity=0.45))
                loaded = ak.load_running_overlay_settings()
                saved_data = ak.json.loads(settings_path.read_text(encoding="utf-8"))

        self.assertEqual(loaded, ak.RunningOverlaySettings(enabled=False, opacity=0.45))
        self.assertEqual(saved_data, {"enabled": False, "opacity": 0.45})

    def test_ui_scale_settings_round_trip_and_clamps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "ui_scale.json"

            with patch.object(ak, "UI_SCALE_CONFIG_PATH", settings_path):
                self.assertEqual(ak.load_ui_scale_settings(), ak.UiScaleSettings())

                ak.save_ui_scale_settings(ak.UiScaleSettings(scale=1.25))
                loaded = ak.load_ui_scale_settings()
                saved_data = ak.json.loads(settings_path.read_text(encoding="utf-8"))

                settings_path.write_text(ak.json.dumps({"scale": 99}, ensure_ascii=False), encoding="utf-8")
                clamped = ak.load_ui_scale_settings()

                settings_path.write_text(ak.json.dumps({"scale": 0.1}, ensure_ascii=False), encoding="utf-8")
                low_clamped = ak.load_ui_scale_settings()

        self.assertEqual(loaded, ak.UiScaleSettings(scale=1.25))
        self.assertEqual(saved_data, {"scale": 1.25})
        self.assertEqual(clamped, ak.UiScaleSettings(scale=ak.UI_SCALE_MAX))
        self.assertEqual(low_clamped, ak.UiScaleSettings(scale=0.5))
        self.assertIn(0.5, ak.UI_SCALE_CHOICES)

    def test_ui_scale_settings_invalid_config_returns_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "ui_scale.json"
            settings_path.write_text("{not json", encoding="utf-8")

            with patch.object(ak, "UI_SCALE_CONFIG_PATH", settings_path):
                loaded = ak.load_ui_scale_settings()

        self.assertEqual(loaded, ak.UiScaleSettings())

    def test_running_overlay_settings_clamps_opacity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "running_overlay.json"
            settings_path.write_text('{"enabled": true, "opacity": 12}', encoding="utf-8")

            with patch.object(ak, "RUNNING_OVERLAY_CONFIG_PATH", settings_path):
                loaded = ak.load_running_overlay_settings()

        self.assertEqual(loaded, ak.RunningOverlaySettings(opacity=ak.RUNNING_OVERLAY_MAX_ALPHA))

    def test_running_overlay_settings_invalid_config_returns_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "running_overlay.json"
            settings_path.write_text("{not json", encoding="utf-8")

            with patch.object(ak, "RUNNING_OVERLAY_CONFIG_PATH", settings_path):
                loaded = ak.load_running_overlay_settings()

        self.assertEqual(loaded, ak.RunningOverlaySettings())

    def test_normalize_discord_user_id_keeps_digits_only(self) -> None:
        self.assertEqual(ak.normalize_discord_user_id(" <@123-abc-456> "), "123456")

    def test_normalize_discord_webhook_url_trims_whitespace_and_angle_brackets(self) -> None:
        self.assertEqual(
            ak.normalize_discord_webhook_url(" <https://discord.com/api/webhooks/abc/token> "),
            "https://discord.com/api/webhooks/abc/token",
        )


class FakeUrlopenResponse:
    def __init__(self, data: bytes) -> None:
        self.stream = io.BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False


class UpdateTests(unittest.TestCase):
    def test_extract_app_version_supports_shared_version_sources(self) -> None:
        self.assertEqual(ak.extract_app_version("1.6.0\n"), "1.6.0")
        self.assertEqual(ak.extract_app_version("APP_VERSION=1.6.0\n"), "1.6.0")
        self.assertEqual(ak.extract_app_version("[Setup]\nAppName=AutoKeyboard\nAppVersion=1.6.0\n"), "1.6.0")

        with self.assertRaisesRegex(ValueError, "找不到版本資訊"):
            ak.extract_app_version("[Setup]\nAppName=AutoKeyboard\n")

    def test_app_version_matches_shared_version_file(self) -> None:
        version_text = (ROOT / "version.txt").read_text(encoding="utf-8")

        self.assertEqual(ak.APP_VERSION, ak.extract_app_version(version_text))

    def test_installer_script_reads_shared_version_file(self) -> None:
        installer_text = (ROOT / "installer.iss").read_text(encoding="utf-8")

        self.assertIn('#define VersionFileHandle FileOpen(AddBackslash(SourcePath) + "version.txt")', installer_text)
        self.assertIn('#define MyAppVersion FileRead(VersionFileHandle)', installer_text)
        self.assertIn('#expr FileClose(VersionFileHandle)', installer_text)
        self.assertIn("AppVersion={#MyAppVersion}", installer_text)

    def test_installer_script_keeps_literal_version_for_legacy_updaters(self) -> None:
        version_text = (ROOT / "version.txt").read_text(encoding="utf-8").strip()
        installer_text = (ROOT / "installer.iss").read_text(encoding="utf-8")

        self.assertIn(f"AppVersion={version_text}", installer_text)
        self.assertEqual(ak.extract_app_version(installer_text), version_text)

    def test_compare_versions_uses_numeric_order(self) -> None:
        self.assertGreater(ak.compare_versions("1.10.0", "1.9.9"), 0)
        self.assertEqual(ak.compare_versions("v1.5.2", "1.5.2.0"), 0)
        self.assertLess(ak.compare_versions("1.5.2", "1.5.3"), 0)

    def test_fetch_latest_update_info_reads_remote_shared_version(self) -> None:
        calls = []

        def fake_urlopen(request, timeout):
            calls.append((request, timeout))
            return FakeUrlopenResponse(b"1.6.0\n")

        with patch("autokeyboard.urllib.request.urlopen", side_effect=fake_urlopen):
            info = ak.fetch_latest_update_info(
                current_version="1.5.2",
                version_url="https://example.test/version.txt",
                installer_url="https://example.test/AutoKeyboard_Setup.exe",
            )

        self.assertTrue(info.has_update)
        self.assertEqual(info.latest_version, "1.6.0")
        self.assertEqual(info.installer_url, "https://example.test/AutoKeyboard_Setup.exe")
        self.assertEqual(calls[0][0].full_url, "https://example.test/version.txt")

    def test_download_update_installer_writes_versioned_exe(self) -> None:
        def fake_urlopen(_request, timeout):
            return FakeUrlopenResponse(b"MZ fake installer")

        with tempfile.TemporaryDirectory() as directory, patch(
            "autokeyboard.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            path = ak.download_update_installer(
                "https://example.test/AutoKeyboard_Setup.exe",
                "1.6.0",
                destination_dir=Path(directory),
            )
            downloaded = path.read_bytes()

        self.assertEqual(path.name, "AutoKeyboard_Setup_1.6.0.exe")
        self.assertEqual(downloaded, b"MZ fake installer")

    def test_launch_update_installer_passes_force_close_arguments(self) -> None:
        installer_path = Path("C:/Temp/AutoKeyboard_Setup.exe")

        with (
            patch.object(ak.platform, "system", return_value="Linux"),
            patch("autokeyboard.subprocess.Popen") as popen,
        ):
            ak.launch_update_installer(installer_path)

        popen.assert_called_once_with(
            [
                str(installer_path),
                "/FORCECLOSEAPPLICATIONS",
                "/NORESTARTAPPLICATIONS",
                "/AUTOKEYBOARD_DELETE_SOURCE_INSTALLER=1",
            ],
            cwd=str(installer_path.parent),
        )


class InstallerScriptTests(unittest.TestCase):
    def test_installer_force_closes_running_app_before_replacing_exe(self) -> None:
        installer_text = (ROOT / "installer.iss").read_text(encoding="utf-8")

        self.assertIn("CloseApplications=force", installer_text)
        self.assertIn("RestartApplications=no", installer_text)
        self.assertIn(
            'Source: "dist\\AutoKeyboard\\AutoKeyboard.exe"; DestDir: "{app}"; '
            "Flags: ignoreversion restartreplace; BeforeInstall: KillRunningAutoKeyboard",
            installer_text,
        )
        self.assertIn(
            'Source: "dist\\AutoKeyboard\\*"; DestDir: "{app}"; '
            'Flags: ignoreversion recursesubdirs createallsubdirs restartreplace; Excludes: "AutoKeyboard.exe"',
            installer_text,
        )
        self.assertIn('Type: filesandordirs; Name: "{app}\\_internal"', installer_text)
        self.assertIn("/F /T /IM AutoKeyboard.exe", installer_text)
        self.assertIn("function CanReplaceAutoKeyboardExe", installer_text)
        self.assertIn("function PrepareToInstall", installer_text)
        self.assertIn("function ShouldDeleteSourceInstaller", installer_text)
        self.assertIn("AUTOKEYBOARD_DELETE_SOURCE_INSTALLER", installer_text)
        self.assertIn("procedure DeinitializeSetup", installer_text)


class TimeFormattingTests(unittest.TestCase):
    def test_seconds_and_text_to_ms(self) -> None:
        self.assertEqual(ak.seconds_to_ms("1.25", "延遲", 1), 1250)
        self.assertEqual(ak.text_to_ms("1,234.4", "延遲"), 1234)

        with self.assertRaisesRegex(ValueError, "必須是數字"):
            ak.seconds_to_ms("abc", "延遲", 1)
        with self.assertRaisesRegex(ValueError, "不能是負數"):
            ak.seconds_to_ms("-1", "延遲", 1)
        with self.assertRaisesRegex(ValueError, "太短"):
            ak.text_to_ms("0", "延遲", minimum_ms=1)

    def test_formats_delays_for_display(self) -> None:
        self.assertEqual(ak.format_number(12.340), "12.34")
        self.assertEqual(ak.format_seconds(1250), "1.25")
        self.assertEqual(ak.format_delay_ms(999), "999 ms")
        self.assertEqual(ak.format_delay_ms(1250), "1.25 秒")
        self.assertEqual(ak.format_delay_ms(60_000), "1 分鐘")
        self.assertEqual(ak.format_delay_ms(61_500), "1 分鐘 1.5 秒")


class RunningOverlayTextTests(unittest.TestCase):
    def test_formats_running_script_names_for_overlay(self) -> None:
        self.assertEqual(ak.format_running_overlay_text([]), "")
        self.assertEqual(ak.format_running_overlay_text([" 炒麵(十分鐘) "]), "執行中\n炒麵(十分鐘)")

    def test_limits_running_script_names_for_overlay(self) -> None:
        names = [f"腳本{i}" for i in range(1, ak.RUNNING_OVERLAY_MAX_SCRIPT_NAMES + 3)]

        text = ak.format_running_overlay_text(names)

        self.assertIn("腳本1", text)
        self.assertIn(f"腳本{ak.RUNNING_OVERLAY_MAX_SCRIPT_NAMES}", text)
        self.assertIn("... 另 2 個", text)


class FakeKeyboard:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ak.KeyAction]] = []

    def key_down_many(self, actions: list[ak.KeyAction]) -> None:
        for action in actions:
            self.calls.append(("down", action))

    def key_up_many(self, actions: list[ak.KeyAction]) -> None:
        for action in actions:
            self.calls.append(("up", action))

    def key_up(self, action: ak.KeyAction) -> None:
        self.calls.append(("up", action))


class FakeRunner:
    def __init__(self) -> None:
        self.stopped = False
        self.join_calls: list[float | None] = []

    def stop(self) -> None:
        self.stopped = True

    def join(self, timeout: float | None = None) -> bool:
        self.join_calls.append(timeout)
        return True


class FakeStringVar:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


class ScriptRunnerTests(unittest.TestCase):
    def test_runner_executes_non_repeating_script_and_publishes_events(self) -> None:
        event_queue: queue.Queue[tuple] = queue.Queue()
        keyboard = FakeKeyboard()
        script = ak.Script(
            id="runner",
            name="runner",
            repeat=False,
            steps=[
                ak.Step(ak.ACTION_KEY_DOWN, key="A"),
                ak.Step(ak.ACTION_DELAY, delay_ms=0),
                ak.Step(ak.ACTION_KEY_UP, key="A"),
            ],
        )

        runner = ak.ScriptRunner(script, keyboard, event_queue)
        runner.start()

        self.assertTrue(runner.join(timeout=2))
        self.assertEqual(
            keyboard.calls,
            [("down", ak.KeyAction(ord("A"))), ("up", ak.KeyAction(ord("A")))],
        )

        events = []
        while not event_queue.empty():
            events.append(event_queue.get_nowait())

        self.assertEqual(events[0], ("started", "runner", ""))
        self.assertIn(("step", "runner", "1. A 按下按鍵"), events)
        self.assertIn(("step", "runner", "2. 延遲 0 ms (維持 1 個按鍵)"), events)
        self.assertIn(("step", "runner", "3. A 放開按鍵"), events)
        self.assertEqual(events[-1], ("stopped", "runner", ""))

    def test_runner_executes_called_script_inline(self) -> None:
        event_queue: queue.Queue[tuple] = queue.Queue()
        keyboard = FakeKeyboard()
        helper = ak.Script(
            id="helper",
            name="helper",
            repeat=True,
            steps=[
                ak.Step(ak.ACTION_KEY_DOWN, key="B"),
                ak.Step(ak.ACTION_DELAY, delay_ms=0),
                ak.Step(ak.ACTION_KEY_UP, key="B"),
            ],
        )
        script = ak.Script(
            id="main",
            name="main",
            repeat=False,
            steps=[
                ak.Step(ak.ACTION_KEY_DOWN, key="A"),
                ak.Step(ak.ACTION_SCRIPT_CALL, script_id="helper"),
                ak.Step(ak.ACTION_KEY_UP, key="A"),
            ],
        )

        runner = ak.ScriptRunner(script, keyboard, event_queue, [script, helper])
        runner.start()

        self.assertTrue(runner.join(timeout=2))
        self.assertEqual(
            keyboard.calls,
            [
                ("down", ak.KeyAction(ord("A"))),
                ("down", ak.KeyAction(ord("B"))),
                ("up", ak.KeyAction(ord("B"))),
                ("up", ak.KeyAction(ord("A"))),
            ],
        )

        events = []
        while not event_queue.empty():
            events.append(event_queue.get_nowait())

        self.assertIn(("step", "main", "2. 呼叫腳本：helper"), events)
        self.assertIn(("step", "main", "2.1. B 按下按鍵"), events)
        self.assertIn(("step", "main", "2.3. B 放開按鍵"), events)

    def test_validate_script_references_rejects_missing_and_circular_calls(self) -> None:
        script = ak.Script(
            id="main",
            name="main",
            repeat=False,
            steps=[ak.Step(ak.ACTION_SCRIPT_CALL, script_id="missing")],
        )

        with self.assertRaisesRegex(ValueError, "找不到要呼叫的腳本"):
            ak.validate_script_references(script, {"main": script})

        script.steps = [ak.Step(ak.ACTION_SCRIPT_CALL, script_id="main")]
        with self.assertRaisesRegex(ValueError, "腳本呼叫形成循環"):
            ak.validate_script_references(script, {"main": script})

    def test_delay_with_held_keys_repeats_until_delay_finishes(self) -> None:
        event_queue: queue.Queue[tuple] = queue.Queue()
        keyboard = FakeKeyboard()
        runner = ak.ScriptRunner(ak.Script(id="delay", name="delay", repeat=False), keyboard, event_queue)
        action = ak.KeyAction(ord("A"))

        stopped = runner._delay_with_held_keys(80, [action, action])

        self.assertFalse(stopped)
        self.assertGreaterEqual(keyboard.calls.count(("down", action)), 1)


class AutoKeyboardAppRuntimeTests(unittest.TestCase):
    def test_recaptcha_detected_stops_all_running_scripts(self) -> None:
        app = object.__new__(ak.AutoKeyboardApp)
        first_runner = FakeRunner()
        second_runner = FakeRunner()
        refreshed = []
        app.runners = {"first": first_runner, "second": second_runner}
        app.current_step = {"first": "執行中"}
        app.recaptcha_status_var = FakeStringVar()
        app.status_var = FakeStringVar()
        app._refresh_script_tree = lambda: refreshed.append(True)

        ak.AutoKeyboardApp._handle_recaptcha_detected(app, "偵測到測謊。")

        self.assertTrue(first_runner.stopped)
        self.assertTrue(second_runner.stopped)
        self.assertEqual(first_runner.join_calls, [ak.RUNNER_STOP_WAIT_SECONDS])
        self.assertEqual(second_runner.join_calls, [ak.RUNNER_STOP_WAIT_SECONDS])
        self.assertEqual(app.current_step, {"first": "停止中", "second": "停止中"})
        self.assertEqual(refreshed, [True])
        self.assertEqual(app.status_var.value, "偵測到測謊。 已中止 2 個執行中的腳本。")
        self.assertEqual(app.recaptcha_status_var.value, app.status_var.value)


class RecaptchaMonitorTests(unittest.TestCase):
    def test_publish_detected_queues_detected_event(self) -> None:
        event_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        monitor = ak.RecaptchaMonitor(event_queue)

        monitor._publish_detected()

        self.assertEqual(event_queue.get_nowait(), ("detected", "偵測到測謊。"))

    def test_monitor_settings_snapshot_normalizes_values(self) -> None:
        event_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        monitor = ak.RecaptchaMonitor(event_queue)

        monitor.set_settings(
            ak.RecaptchaMonitorSettings(
                enabled=True,
                recipient_name=" 羅總 ",
                only_maplestory_window=False,
            )
        )

        self.assertEqual(
            monitor._settings_snapshot(),
            ak.RecaptchaMonitorSettings(
                enabled=True,
                recipient_name="羅總",
                only_maplestory_window=False,
            ),
        )

    def test_monitor_settings_snapshot_requires_selected_recipient(self) -> None:
        event_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        monitor = ak.RecaptchaMonitor(event_queue)

        monitor.set_settings(ak.RecaptchaMonitorSettings(enabled=True, recipient_name="不存在"))

        self.assertEqual(
            monitor._settings_snapshot(),
            ak.RecaptchaMonitorSettings(enabled=True, recipient_name="", only_maplestory_window=True),
        )

    def test_post_discord_webhook_uses_configured_url(self) -> None:
        event_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        monitor = ak.RecaptchaMonitor(event_queue)
        webhook_url = "https://discord.com/api/webhooks/custom/token"

        class FakeResponse:
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

        with (
            patch.object(monitor, "_screenshot_jpeg_bytes", return_value=b"jpg-bytes"),
            patch("autokeyboard.urllib.request.urlopen", return_value=FakeResponse()) as urlopen,
        ):
            monitor._post_discord_webhook(webhook_url, "123", object())

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, webhook_url)

    def test_discord_multipart_body_contains_payload_and_file(self) -> None:
        event_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        monitor = ak.RecaptchaMonitor(event_queue)

        body, content_type = monitor._discord_multipart_body(
            payload={"content": "測試通知", "allowed_mentions": {"users": ["123"]}},
            screenshot_bytes=b"png-bytes",
            filename="detected.png",
        )

        self.assertIn("multipart/form-data; boundary=", content_type)
        self.assertIn(b'name="payload_json"', body)
        self.assertIn("測試通知".encode("utf-8"), body)
        self.assertIn(b'filename="detected.png"', body)
        self.assertIn(b"png-bytes", body)

    def test_publish_error_throttles_duplicate_messages(self) -> None:
        event_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        monitor = ak.RecaptchaMonitor(event_queue)

        monitor._publish_error("same error")
        monitor._publish_error("same error")
        monitor._last_error_at = time.monotonic() - 31
        monitor._publish_error("same error")

        events = []
        while not event_queue.empty():
            events.append(event_queue.get_nowait())

        self.assertEqual(events, [("error", "same error"), ("error", "same error")])

    def test_queue_detected_notification_uses_one_second_cadence(self) -> None:
        event_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        monitor = ak.RecaptchaMonitor(event_queue)
        started = []

        class FakeThread:
            def __init__(self, *, target, args, name, daemon):
                self.target = target
                self.args = args

            def start(self):
                started.append(self.args)
                self.target(*self.args)

        with (
            patch("autokeyboard.time.monotonic", side_effect=[100.0, 100.5, 101.0]),
            patch("autokeyboard.threading.Thread", FakeThread),
            patch.object(monitor, "_post_discord_webhook"),
        ):
            monitor._queue_detected_notification("https://discord.com/api/webhooks/custom/token", "123", object())
            monitor._queue_detected_notification("https://discord.com/api/webhooks/custom/token", "123", object())
            monitor._queue_detected_notification("https://discord.com/api/webhooks/custom/token", "123", object())

        self.assertEqual(len(started), 2)


if __name__ == "__main__":
    unittest.main()
